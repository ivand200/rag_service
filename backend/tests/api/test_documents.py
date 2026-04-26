from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_chat_service, get_embedding_service, get_storage_service
from app.config import Settings, get_settings
from app.db.models import Base, Document, IngestionJob, Workspace
from app.db.session import get_db_session
from app.main import create_app
from tests.api.auth_helpers import TEST_CLERK_PUBLIC_KEY, auth_headers


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def ensure_bucket(self) -> None:
        return None

    async def upload_bytes(self, key: str, content: bytes, content_type: str | None) -> None:
        self.objects[key] = content

    async def download_bytes(self, key: str) -> bytes:
        return self.objects[key]


class FakeEmbeddingService:
    def __init__(self, embeddings: dict[str, list[float]]) -> None:
        self.embeddings = embeddings

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embeddings[text] for text in texts]


class FakeChatService:
    not_supported_token = "NOT_SUPPORTED"

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text

    async def generate_answer(self, *, question: str, context: str, history: list[object]) -> str:
        return self.response_text


def build_settings(**overrides: object) -> Settings:
    return Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        database_url="sqlite+pysqlite:///:memory:",
        s3_endpoint_url="http://localhost:9000",
        clerk_jwt_public_key=TEST_CLERK_PUBLIC_KEY,
        **overrides,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def documents_harness() -> AsyncIterator[
    tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage]
]:
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
    storage = FakeStorage()

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_settings] = lambda: build_settings()
    app.dependency_overrides[get_storage_service] = lambda: storage
    app.dependency_overrides[get_embedding_service] = lambda: FakeEmbeddingService({})
    app.dependency_overrides[get_chat_service] = lambda: FakeChatService("unused")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client, session_factory, storage

    await engine.dispose()


async def _override_documents_dependencies(
    app_client: AsyncClient,
    *,
    settings: Settings | None = None,
    embedding_service: FakeEmbeddingService | None = None,
    chat_service: FakeChatService | None = None,
) -> None:
    app = app_client._transport.app  # type: ignore[attr-defined]
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    if embedding_service is not None:
        app.dependency_overrides[get_embedding_service] = lambda: embedding_service
    if chat_service is not None:
        app.dependency_overrides[get_chat_service] = lambda: chat_service


async def _seed_document(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    filename: str = "notes.txt",
    status: str = "pending",
    content_type: str = "text/plain",
    error_summary: str | None = None,
) -> int:
    async with session_factory() as session:
        workspace = await session.scalar(select(Workspace).limit(1))
        if workspace is None:
            workspace = Workspace(name="Personal Workspace")
            session.add(workspace)
            await session.flush()
        document = Document(
            workspace_id=workspace.id,
            filename=filename,
            content_type=content_type,
            storage_key=f"documents/{filename}",
            status=status,
            error_summary=error_summary,
            content_hash=f"hash-{filename}",
        )
        session.add(document)
        await session.flush()
        session.add(IngestionJob(document_id=document.id, status="queued", attempt_count=0))
        await session.commit()
        return document.id


@pytest.mark.anyio
async def test_upload_document_returns_pending_summary(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, _, _ = documents_harness

    response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"Hello RAG world", "text/plain")},
        headers=auth_headers(),
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "notes.txt"
    assert response.json()["status"] == "pending"


@pytest.mark.anyio
async def test_upload_document_rejects_unsupported_file_type(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, _, _ = documents_harness

    response = await client.post(
        "/api/documents",
        files={"file": ("notes.docx", b"Hello RAG world", "application/vnd.openxmlformats")},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unsupported file type"}


@pytest.mark.anyio
async def test_upload_document_rejects_empty_file(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, _, _ = documents_harness

    response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"", "text/plain")},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "file is empty"}


@pytest.mark.anyio
async def test_upload_document_rejects_file_larger_than_limit(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, _, _ = documents_harness
    await _override_documents_dependencies(
        client,
        settings=build_settings(upload_max_bytes=4),
    )

    response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"Hello", "text/plain")},
        headers=auth_headers(),
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "file exceeds upload limit"}


@pytest.mark.anyio
async def test_list_documents_returns_uploaded_document_statuses(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, session_factory, _ = documents_harness
    await _seed_document(session_factory, filename="notes.txt", status="pending")
    await _seed_document(
        session_factory,
        filename="ready.md",
        status="ready",
        content_type="text/markdown",
    )

    response = await client.get("/api/documents", headers=auth_headers())

    assert response.status_code == 200
    assert [
        (document["filename"], document["status"]) for document in response.json()["documents"]
    ] == [("notes.txt", "pending"), ("ready.md", "ready")]


@pytest.mark.anyio
async def test_get_document_returns_persisted_document_details(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, session_factory, _ = documents_harness
    document_id = await _seed_document(
        session_factory,
        filename="failed.pdf",
        status="failed",
        content_type="application/pdf",
        error_summary="parser failed",
    )

    response = await client.get(f"/api/documents/{document_id}", headers=auth_headers())

    assert response.status_code == 200
    assert response.json() == {
        "id": document_id,
        "filename": "failed.pdf",
        "content_type": "application/pdf",
        "storage_key": "documents/failed.pdf",
        "status": "failed",
        "error_summary": "parser failed",
        "created_at": response.json()["created_at"],
        "updated_at": response.json()["updated_at"],
    }


@pytest.mark.anyio
async def test_uploaded_document_is_not_searchable_until_ingestion_completes(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, _, _ = documents_harness
    await _override_documents_dependencies(
        client,
        embedding_service=FakeEmbeddingService(
            {"What does the uploaded file say?": [1.0] + [0.0] * 1023}
        ),
        chat_service=FakeChatService("This should not be used"),
    )

    session_response = await client.post("/api/chat/sessions", headers=auth_headers())
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"Pending document content", "text/plain")},
        headers=auth_headers(),
    )
    chat_response = await client.post(
        "/api/chat/messages",
        json={
            "session_id": session_response.json()["id"],
            "message": "What does the uploaded file say?",
        },
        headers=auth_headers(),
    )

    assert session_response.status_code == 201
    assert upload_response.status_code == 201
    assert upload_response.json()["status"] == "pending"
    assert (chat_response.json()["grounded"], chat_response.json()["citations"]) == (False, [])


@pytest.mark.anyio
async def test_documents_require_authentication(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, _, _ = documents_harness

    response = await client.get("/api/documents")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


@pytest.mark.anyio
async def test_document_upload_requires_authentication(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, _, _ = documents_harness

    response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"Hello RAG world", "text/plain")},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


@pytest.mark.anyio
async def test_get_document_requires_authentication(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, session_factory, _ = documents_harness
    document_id = await _seed_document(session_factory)

    response = await client.get(f"/api/documents/{document_id}")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


@pytest.mark.anyio
async def test_documents_reject_invalid_bearer_token(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, _, _ = documents_harness

    response = await client.get(
        "/api/documents",
        headers={"Authorization": "Bearer definitely-not-a-jwt"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid authentication token"}


@pytest.mark.anyio
async def test_authenticated_users_share_the_same_document_library(
    documents_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession], FakeStorage],
) -> None:
    client, _, _ = documents_harness

    upload_response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"Shared library content", "text/plain")},
        headers=auth_headers(user_id="user_alpha"),
    )
    list_response = await client.get(
        "/api/documents",
        headers=auth_headers(user_id="user_beta"),
    )

    assert upload_response.status_code == 201
    assert [document["filename"] for document in list_response.json()["documents"]] == ["notes.txt"]
