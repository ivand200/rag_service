from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_chat_service, get_embedding_service
from app.config import Settings, get_settings
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
    Workspace,
)
from app.db.session import get_db_session
from app.main import create_app
from tests.api.auth_helpers import TEST_CLERK_PUBLIC_KEY, auth_headers

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017


class FakeEmbeddingService:
    def __init__(self, embeddings: dict[str, list[float]]) -> None:
        self.embeddings = embeddings

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embeddings[text] for text in texts]


class FakeChatService:
    not_supported_token = "NOT_SUPPORTED"

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.history_contents: list[str] = []

    async def generate_answer(
        self,
        *,
        question: str,
        context: str,
        history: list[ChatMessage],
    ) -> str:
        self.history_contents = [message.content for message in history]
        return self.response_text


def build_settings() -> Settings:
    return Settings(
        dashscope_api_key="test-key",
        database_url="sqlite+pysqlite:///:memory:",
        s3_endpoint_url="http://localhost:9000",
        clerk_jwt_public_key=TEST_CLERK_PUBLIC_KEY,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def chat_harness() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    app = create_app(bootstrap_workspace=False)
    app.state.embedding_service = FakeEmbeddingService(
        {"unused": [1.0] + [0.0] * (EMBEDDING_VECTOR_DIMENSIONS - 1)}
    )
    app.state.chat_service = FakeChatService("unused")

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_settings] = build_settings
    app.dependency_overrides[get_embedding_service] = lambda: app.state.embedding_service
    app.dependency_overrides[get_chat_service] = lambda: app.state.chat_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client, session_factory

    await engine.dispose()


async def _set_chat_services(
    client: AsyncClient,
    *,
    embedding_service: FakeEmbeddingService,
    chat_service: FakeChatService,
) -> FakeChatService:
    app = client._transport.app  # type: ignore[attr-defined]
    app.state.embedding_service = embedding_service
    app.state.chat_service = chat_service
    return chat_service


async def _seed_ready_document(session_factory: async_sessionmaker[AsyncSession]) -> int:
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
            filename="notes.txt",
            content_type="text/plain",
            storage_key="documents/notes.txt",
            status=DocumentStatus.ready.value,
            content_hash="hash",
        )
        session.add(document)
        await session.flush()
        session.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=0,
                text="Paris is the capital of France.",
                snippet="Paris is the capital of France.",
                embedding=[1.0] + [0.0] * (EMBEDDING_VECTOR_DIMENSIONS - 1),
                token_count=6,
                page_number=1,
                section_label="Overview",
            )
        )
        await session.commit()
        return workspace.id


async def _create_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: int,
    clerk_user_id: str,
    title: str = "New session",
    updated_at: datetime | None = None,
) -> ChatSession:
    async with session_factory() as session:
        chat_session = ChatSession(
            workspace_id=workspace_id,
            clerk_user_id=clerk_user_id,
            title=title,
        )
        if updated_at is not None:
            chat_session.updated_at = updated_at
        session.add(chat_session)
        await session.commit()
        await session.refresh(chat_session)
        return chat_session


async def _add_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: int,
    session_id: int | None,
    clerk_user_id: str | None,
    role: str,
    content: str,
    grounded: bool = False,
) -> None:
    async with session_factory() as session:
        session.add(
            ChatMessage(
                workspace_id=workspace_id,
                session_id=session_id,
                clerk_user_id=clerk_user_id,
                role=role,
                content=content,
                grounded=grounded,
                citations_json=[],
            )
        )
        await session.commit()


@pytest.mark.anyio
async def test_list_chat_sessions_auto_creates_first_session_for_new_user(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    await _seed_ready_document(session_factory)

    response = await client.get("/api/chat/sessions", headers=auth_headers(user_id="user_123"))

    assert response.status_code == 200
    assert [session["title"] for session in response.json()["sessions"]] == ["New session"]


@pytest.mark.anyio
async def test_list_chat_sessions_returns_only_owned_sessions_in_recent_first_order(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    workspace_id = await _seed_ready_document(session_factory)
    base_time = datetime.now(UTC)
    older = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
        title="Older",
        updated_at=base_time - timedelta(hours=1),
    )
    newer = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
        title="Newer",
        updated_at=base_time,
    )
    await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_other",
        title="Other user",
        updated_at=base_time + timedelta(hours=1),
    )

    response = await client.get("/api/chat/sessions", headers=auth_headers(user_id="user_123"))

    assert response.status_code == 200
    assert [(item["id"], item["title"]) for item in response.json()["sessions"]] == [
        (newer.id, "Newer"),
        (older.id, "Older"),
    ]


@pytest.mark.anyio
async def test_create_chat_session_creates_new_session_then_reuses_existing_empty_one(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    workspace_id = await _seed_ready_document(session_factory)
    existing = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
        title="Existing work",
    )
    await _add_message(
        session_factory,
        workspace_id=workspace_id,
        session_id=existing.id,
        clerk_user_id="user_123",
        role="user",
        content="Earlier question",
    )

    first_response = await client.post(
        "/api/chat/sessions",
        headers=auth_headers(user_id="user_123"),
    )
    second_response = await client.post(
        "/api/chat/sessions",
        headers=auth_headers(user_id="user_123"),
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    first_session_id = first_response.json()["id"]
    second_session_id = second_response.json()["id"]
    assert second_session_id == first_session_id
    assert second_session_id != existing.id

    async with session_factory() as session:
        owned_sessions = list(
            await session.scalars(
                select(ChatSession)
                .where(ChatSession.clerk_user_id == "user_123")
                .order_by(ChatSession.id)
            )
        )

    assert [item.id for item in owned_sessions] == [existing.id, first_session_id]


@pytest.mark.anyio
async def test_create_chat_session_creates_fresh_session_when_latest_session_is_not_empty(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    workspace_id = await _seed_ready_document(session_factory)
    base_time = datetime.now(UTC)
    older_empty = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
        title="Older empty",
        updated_at=base_time - timedelta(hours=1),
    )
    latest_active = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
        title="Latest active",
        updated_at=base_time,
    )
    await _add_message(
        session_factory,
        workspace_id=workspace_id,
        session_id=latest_active.id,
        clerk_user_id="user_123",
        role="user",
        content="Keep this thread active",
    )

    response = await client.post("/api/chat/sessions", headers=auth_headers(user_id="user_123"))

    assert response.status_code == 201
    assert response.json()["id"] not in {older_empty.id, latest_active.id}


@pytest.mark.anyio
async def test_list_chat_messages_returns_only_selected_session_history(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    workspace_id = await _seed_ready_document(session_factory)
    active = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
        title="Active",
    )
    other = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
        title="Other",
    )
    await _add_message(
        session_factory,
        workspace_id=workspace_id,
        session_id=active.id,
        clerk_user_id="user_123",
        role="assistant",
        content="Active answer",
        grounded=True,
    )
    await _add_message(
        session_factory,
        workspace_id=workspace_id,
        session_id=other.id,
        clerk_user_id="user_123",
        role="assistant",
        content="Other answer",
        grounded=True,
    )
    await _add_message(
        session_factory,
        workspace_id=workspace_id,
        session_id=None,
        clerk_user_id="user_123",
        role="assistant",
        content="Legacy hidden answer",
        grounded=True,
    )

    response = await client.get(
        f"/api/chat/messages?session_id={active.id}",
        headers=auth_headers(user_id="user_123"),
    )

    assert response.status_code == 200
    assert [message["content"] for message in response.json()["messages"]] == ["Active answer"]


@pytest.mark.anyio
async def test_chat_message_routes_return_safe_not_found_for_non_owned_session(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    await _set_chat_services(
        client,
        embedding_service=FakeEmbeddingService(
            {"What is the capital of France?": [1.0] + [0.0] * 1023}
        ),
        chat_service=FakeChatService("Paris is the capital of France."),
    )
    workspace_id = await _seed_ready_document(session_factory)
    other_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_other",
    )

    history_response = await client.get(
        f"/api/chat/messages?session_id={other_session.id}",
        headers=auth_headers(user_id="user_123"),
    )
    create_response = await client.post(
        "/api/chat/messages",
        json={"session_id": other_session.id, "message": "What is the capital of France?"},
        headers=auth_headers(user_id="user_123"),
    )

    assert history_response.status_code == 404
    assert history_response.json() == {"detail": "chat session not found"}
    assert create_response.status_code == 404
    assert create_response.json() == {"detail": "chat session not found"}


@pytest.mark.anyio
async def test_posted_chat_exchange_persists_in_session_and_enqueues_single_title_job(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    await _set_chat_services(
        client,
        embedding_service=FakeEmbeddingService(
            {"What is the capital of France?": [1.0] + [0.0] * 1023}
        ),
        chat_service=FakeChatService("Paris is the capital of France."),
    )
    workspace_id = await _seed_ready_document(session_factory)
    chat_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
    )

    first_response = await client.post(
        "/api/chat/messages",
        json={"session_id": chat_session.id, "message": "What is the capital of France?"},
        headers=auth_headers(user_id="user_123"),
    )
    second_response = await client.post(
        "/api/chat/messages",
        json={"session_id": chat_session.id, "message": "What is the capital of France?"},
        headers=auth_headers(user_id="user_123"),
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    async with session_factory() as session:
        persisted_messages = list(
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == chat_session.id)
                .order_by(ChatMessage.id)
            )
        )
        title_jobs = list(
            await session.scalars(
                select(ChatSessionTitleJob).where(ChatSessionTitleJob.session_id == chat_session.id)
            )
        )

    assert [(item.role, item.clerk_user_id) for item in persisted_messages] == [
        ("user", "user_123"),
        ("assistant", "user_123"),
        ("user", "user_123"),
        ("assistant", "user_123"),
    ]
    assert len(title_jobs) == 1


@pytest.mark.anyio
async def test_chat_exchange_uses_only_selected_session_history_and_shared_retrieval(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    chat_service = await _set_chat_services(
        client,
        embedding_service=FakeEmbeddingService(
            {"What is the capital of France?": [1.0] + [0.0] * 1023}
        ),
        chat_service=FakeChatService("Paris is the capital of France."),
    )
    workspace_id = await _seed_ready_document(session_factory)
    first_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
        title="First",
    )
    second_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
        title="Second",
    )
    await _add_message(
        session_factory,
        workspace_id=workspace_id,
        session_id=first_session.id,
        clerk_user_id="user_123",
        role="assistant",
        content="Earlier answer from first session",
        grounded=True,
    )

    response = await client.post(
        "/api/chat/messages",
        json={"session_id": second_session.id, "message": "What is the capital of France?"},
        headers=auth_headers(user_id="user_123"),
    )

    assert response.status_code == 201
    assert [(item["document_name"], item["snippet"]) for item in response.json()["citations"]] == [
        ("notes.txt", "Paris is the capital of France.")
    ]
    assert chat_service.history_contents == []


@pytest.mark.anyio
async def test_chat_routes_require_authentication(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    workspace_id = await _seed_ready_document(session_factory)
    chat_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
    )

    session_list_response = await client.get("/api/chat/sessions")
    create_session_response = await client.post("/api/chat/sessions")
    history_response = await client.get(f"/api/chat/messages?session_id={chat_session.id}")
    create_message_response = await client.post(
        "/api/chat/messages",
        json={"session_id": chat_session.id, "message": "What is the capital of France?"},
    )

    for response in (
        session_list_response,
        create_session_response,
        history_response,
        create_message_response,
    ):
        assert response.status_code == 401
        assert response.json() == {"detail": "authentication required"}
