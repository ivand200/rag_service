from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.constants import (
    EMBEDDING_VECTOR_DIMENSIONS,
    SINGLETON_WORKSPACE_ID,
    SINGLETON_WORKSPACE_NAME,
)
from app.db.models import (
    Base,
    ChatMessage,
    ChatSession,
    ChatSessionTitleJob,
    Document,
    DocumentChunk,
    DocumentStatus,
    IngestionJob,
    JobStatus,
    MessageRole,
    Workspace,
)
from app.services.chat import claim_next_title_job, process_title_job
from app.services.document_repository import DocumentRepository
from app.services.ingestion import claim_next_job, process_job
from app.worker import main as worker_main

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017


def build_settings(**overrides: object) -> Settings:
    return Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        database_url="sqlite+pysqlite:///:memory:",
        s3_endpoint_url="http://localhost:9000",
        **overrides,
    )


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    async def download_bytes(self, key: str) -> bytes:
        return self.objects[key]


class FakeEmbeddingService:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1)] * EMBEDDING_VECTOR_DIMENSIONS for index, _ in enumerate(texts)]


class DeletingEmbeddingService(FakeEmbeddingService):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        document_id: int,
    ) -> None:
        self.session_factory = session_factory
        self.document_id = document_id

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        async with self.session_factory() as session:
            await DocumentRepository(session).hard_delete_document(
                document_id=self.document_id,
                workspace_id=SINGLETON_WORKSPACE_ID,
            )
        return await super().embed_texts(texts)


class FakeChatService:
    def __init__(self, title: str = "France capital thread") -> None:
        self.title = title
        self.first_messages: list[str] = []

    async def generate_session_title(self, *, first_user_message: str) -> str:
        self.first_messages.append(first_user_message)
        return self.title


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    testing_session_local = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield testing_session_local
    finally:
        await engine.dispose()


async def seed_job(
    session_factory: async_sessionmaker[AsyncSession],
    filename: str,
    *,
    created_at: datetime | None = None,
) -> tuple[int, int, str]:
    async with session_factory() as session:
        workspace = await session.get(Workspace, SINGLETON_WORKSPACE_ID)
        if workspace is None:
            workspace = Workspace(
                id=SINGLETON_WORKSPACE_ID,
                name=SINGLETON_WORKSPACE_NAME,
            )
            session.add(workspace)
            await session.flush()
        document = Document(
            workspace_id=workspace.id,
            filename=filename,
            content_type="text/plain",
            storage_key=f"documents/{filename}",
            status=DocumentStatus.pending.value,
            content_hash=f"hash-{filename}",
        )
        session.add(document)
        await session.flush()
        job = IngestionJob(
            document_id=document.id,
            status=JobStatus.queued.value,
            attempt_count=0,
        )
        if created_at is not None:
            job.created_at = created_at
        session.add(job)
        await session.commit()
        return job.id, document.id, document.storage_key


async def seed_title_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    title: str = "New session",
) -> tuple[int, int]:
    async with session_factory() as session:
        workspace = await session.get(Workspace, SINGLETON_WORKSPACE_ID)
        if workspace is None:
            workspace = Workspace(
                id=SINGLETON_WORKSPACE_ID,
                name=SINGLETON_WORKSPACE_NAME,
            )
            session.add(workspace)
            await session.flush()
        chat_session = ChatSession(
            workspace_id=workspace.id,
            clerk_user_id="user_123",
            title=title,
        )
        session.add(chat_session)
        await session.flush()
        session.add(
            ChatMessage(
                workspace_id=workspace.id,
                session_id=chat_session.id,
                clerk_user_id="user_123",
                role=MessageRole.user.value,
                content="What is the capital of France?",
                grounded=False,
                citations_json=[],
            )
        )
        title_job = ChatSessionTitleJob(
            session_id=chat_session.id,
            status=JobStatus.queued.value,
            attempt_count=0,
        )
        session.add(title_job)
        await session.commit()
        return title_job.id, chat_session.id


@pytest.mark.anyio
async def test_ingestion_success_marks_document_ready_and_indexes_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, document_id, storage_key = await seed_job(session_factory, "notes.txt")
    settings = build_settings()

    async with session_factory() as claim_session:
        claimed_job_id = await claim_next_job(claim_session, settings)

    async with session_factory() as process_session:
        await process_job(
            process_session,
            job_id,
            settings,
            FakeStorage({storage_key: b"hello world " * 200}),
            FakeEmbeddingService(),
        )

    async with session_factory() as verify_session:
        document = await verify_session.get(Document, document_id)
        job = await verify_session.get(IngestionJob, job_id)
        chunk_count = await verify_session.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
        )

    assert claimed_job_id == job_id
    assert document is not None and document.status == DocumentStatus.ready.value
    assert job is not None and job.status == JobStatus.completed.value
    assert chunk_count and chunk_count > 0


@pytest.mark.anyio
async def test_ingestion_failure_requeues_before_final_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, document_id, storage_key = await seed_job(session_factory, "broken.pdf")
    settings = build_settings()

    async with session_factory() as claim_session:
        await claim_next_job(claim_session, settings)

    async with session_factory() as process_session:
        await process_job(
            process_session,
            job_id,
            settings,
            FakeStorage({storage_key: b"%PDF-1.4 invalid"}),
            FakeEmbeddingService(),
        )

    async with session_factory() as verify_session:
        document = await verify_session.get(Document, document_id)
        job = await verify_session.get(IngestionJob, job_id)

    assert document is not None and document.status == DocumentStatus.pending.value
    assert job is not None and job.status == JobStatus.queued.value
    assert job is not None and job.last_error is not None


@pytest.mark.anyio
async def test_ingestion_failure_marks_document_failed_after_final_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, document_id, storage_key = await seed_job(session_factory, "broken.pdf")
    settings = build_settings(ingestion_max_retries=1)

    async with session_factory() as claim_session:
        await claim_next_job(claim_session, settings)

    async with session_factory() as process_session:
        await process_job(
            process_session,
            job_id,
            settings,
            FakeStorage({storage_key: b"%PDF-1.4 invalid"}),
            FakeEmbeddingService(),
        )

    async with session_factory() as verify_session:
        document = await verify_session.get(Document, document_id)
        job = await verify_session.get(IngestionJob, job_id)

    assert document is not None and document.status == DocumentStatus.failed.value
    assert job is not None and job.status == JobStatus.failed.value
    assert job is not None and job.completed_at is not None


@pytest.mark.anyio
async def test_ingestion_exits_cleanly_when_claimed_document_is_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, document_id, storage_key = await seed_job(session_factory, "removed.txt")
    settings = build_settings()

    async with session_factory() as claim_session:
        await claim_next_job(claim_session, settings)
    async with session_factory() as delete_session:
        await DocumentRepository(delete_session).hard_delete_document(
            document_id=document_id,
            workspace_id=SINGLETON_WORKSPACE_ID,
        )

    async with session_factory() as process_session:
        await process_job(
            process_session,
            job_id,
            settings,
            FakeStorage({storage_key: b"hello world " * 200}),
            FakeEmbeddingService(),
        )

    async with session_factory() as verify_session:
        document = await verify_session.get(Document, document_id)
        job = await verify_session.get(IngestionJob, job_id)

    assert document is None
    assert job is None


@pytest.mark.anyio
async def test_ingestion_exits_cleanly_when_claimed_job_is_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, document_id, storage_key = await seed_job(session_factory, "jobless.txt")
    settings = build_settings()

    async with session_factory() as claim_session:
        await claim_next_job(claim_session, settings)
    async with session_factory() as delete_session:
        await delete_session.execute(delete(IngestionJob).where(IngestionJob.id == job_id))
        await delete_session.commit()

    async with session_factory() as process_session:
        await process_job(
            process_session,
            job_id,
            settings,
            FakeStorage({storage_key: b"hello world " * 200}),
            FakeEmbeddingService(),
        )

    async with session_factory() as verify_session:
        document = await verify_session.get(Document, document_id)
        job = await verify_session.get(IngestionJob, job_id)

    assert document is not None and document.status == DocumentStatus.processing.value
    assert job is None


@pytest.mark.anyio
async def test_ingestion_does_not_mark_document_ready_when_deleted_during_processing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, document_id, storage_key = await seed_job(session_factory, "race.txt")
    settings = build_settings()

    async with session_factory() as claim_session:
        await claim_next_job(claim_session, settings)

    async with session_factory() as process_session:
        await process_job(
            process_session,
            job_id,
            settings,
            FakeStorage({storage_key: b"hello world " * 200}),
            DeletingEmbeddingService(session_factory, document_id=document_id),
        )

    async with session_factory() as verify_session:
        document = await verify_session.get(Document, document_id)
        job = await verify_session.get(IngestionJob, job_id)
        chunk_count = await verify_session.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
        )

    assert document is None
    assert (job, chunk_count) == (None, 0)


@pytest.mark.anyio
async def test_claims_queued_ingestion_backlog_in_created_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_created_at = datetime.now(UTC)
    first_job_id, _, _ = await seed_job(
        session_factory,
        "first.txt",
        created_at=first_created_at,
    )
    second_job_id, _, _ = await seed_job(
        session_factory,
        "second.txt",
        created_at=first_created_at + timedelta(seconds=1),
    )
    settings = build_settings()

    async with session_factory() as first_claim_session:
        first_claim = await claim_next_job(first_claim_session, settings)

    async with session_factory() as second_claim_session:
        second_claim = await claim_next_job(second_claim_session, settings)

    assert first_claim == first_job_id
    assert second_claim == second_job_id


@pytest.mark.anyio
async def test_title_job_success_updates_session_title_and_completes_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, chat_session_id = await seed_title_job(session_factory)
    settings = build_settings()
    chat_service = FakeChatService("France capital")

    async with session_factory() as claim_session:
        claimed_job_id = await claim_next_title_job(claim_session, settings)

    async with session_factory() as process_session:
        await process_title_job(process_session, job_id, settings, chat_service)

    async with session_factory() as verify_session:
        chat_session = await verify_session.get(ChatSession, chat_session_id)
        job = await verify_session.get(ChatSessionTitleJob, job_id)

    assert claimed_job_id == job_id
    assert chat_session is not None and chat_session.title == "France capital"
    assert job is not None and job.status == JobStatus.completed.value
    assert chat_service.first_messages == ["What is the capital of France?"]


@pytest.mark.anyio
async def test_title_job_failure_requeues_then_marks_failed_after_final_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, chat_session_id = await seed_title_job(session_factory)
    chat_service = FakeChatService()

    async def raise_error(*, first_user_message: str) -> str:
        raise RuntimeError(f"provider error for {first_user_message}")

    chat_service.generate_session_title = raise_error  # type: ignore[method-assign]
    settings = build_settings(ingestion_max_retries=2)

    async with session_factory() as first_claim_session:
        first_claim = await claim_next_title_job(first_claim_session, settings)

    async with session_factory() as first_process_session:
        await process_title_job(first_process_session, job_id, settings, chat_service)

    async with session_factory() as mid_verify_session:
        mid_job = await mid_verify_session.get(ChatSessionTitleJob, job_id)
        mid_chat_session = await mid_verify_session.get(ChatSession, chat_session_id)

    async with session_factory() as second_claim_session:
        second_claim = await claim_next_title_job(second_claim_session, settings)

    async with session_factory() as final_process_session:
        await process_title_job(final_process_session, job_id, settings, chat_service)

    async with session_factory() as final_verify_session:
        final_job = await final_verify_session.get(ChatSessionTitleJob, job_id)
        final_chat_session = await final_verify_session.get(ChatSession, chat_session_id)

    assert first_claim == job_id
    assert mid_job is not None and mid_job.status == JobStatus.queued.value
    assert mid_chat_session is not None and mid_chat_session.title == "New session"
    assert second_claim == job_id
    assert final_job is not None and final_job.status == JobStatus.failed.value
    assert final_chat_session is not None and final_chat_session.title == "New session"


@pytest.mark.anyio
async def test_worker_processes_one_ingestion_job_before_checking_title_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_log: list[tuple[str, object]] = []
    fake_session_factory = object()

    class StopWorker(KeyboardInterrupt):
        pass

    async def fake_claim_job(
        session_factory: object,
        claimer: Callable[..., AsyncIterator[int | None]],
    ) -> int | None:
        assert session_factory is fake_session_factory
        if len(call_log) == 0:
            call_log.append(("claim", "ingestion"))
            return 41
        call_log.append(("claim", "unexpected"))
        return None

    async def fake_process_claimed_job(**kwargs: object) -> None:
        assert kwargs["session_factory"] is fake_session_factory
        call_log.append(("process", kwargs.get("job_type", "ingestion")))
        raise StopWorker

    async def fake_dispose() -> None:
        call_log.append(("dispose", "engine"))

    monkeypatch.setattr(worker_main, "get_async_session_factory", lambda: fake_session_factory)
    monkeypatch.setattr(worker_main, "_claim_job", fake_claim_job)
    monkeypatch.setattr(worker_main, "_process_claimed_job", fake_process_claimed_job)
    monkeypatch.setattr(worker_main, "dispose_async_engine", fake_dispose)
    monkeypatch.setattr(worker_main, "StorageService", lambda settings: object())
    monkeypatch.setattr(worker_main, "create_embedding_service", lambda settings: object())
    monkeypatch.setattr(worker_main, "create_chat_service", lambda settings: object())
    monkeypatch.setattr(worker_main, "configure_logging", lambda: None)
    monkeypatch.setattr(worker_main, "log_event", lambda *args, **kwargs: None)

    with pytest.raises(StopWorker):
        await worker_main.run_forever()

    assert call_log == [
        ("claim", "ingestion"),
        ("process", "ingestion"),
        ("dispose", "engine"),
    ]
