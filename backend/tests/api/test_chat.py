from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from types import SimpleNamespace

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
from app.services.llm import ChatService, RetrievalPlan, RetrievalPlanProviderSchema
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

    def __init__(
        self,
        response_text: str,
        *,
        retrieval_query: str | None = None,
        retrieval_broad: bool = False,
    ) -> None:
        self.response_text = response_text
        self.retrieval_query = retrieval_query
        self.retrieval_broad = retrieval_broad
        self.history_contents: list[str] = []
        self.planned_messages: list[str] = []

    async def generate_retrieval_plan(
        self,
        *,
        message: str,
        history: list[ChatMessage],
    ) -> RetrievalPlan:
        del history
        self.planned_messages.append(message)
        return RetrievalPlan(
            query=self.retrieval_query or message,
            broad=self.retrieval_broad,
        )

    async def generate_answer(
        self,
        *,
        question: str,
        context: str,
        history: list[ChatMessage],
    ) -> str:
        self.history_contents = [message.content for message in history]
        return self.response_text


class FakeStructuredChatCompletionsAPI:
    def __init__(
        self,
        *,
        parsed: RetrievalPlanProviderSchema,
        answer: str,
    ) -> None:
        self.parsed = parsed
        self.answer = answer
        self.parse_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []

    async def parse(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: type[RetrievalPlanProviderSchema],
    ) -> object:
        self.parse_calls.append(
            {
                "model": model,
                "messages": messages,
                "response_format": response_format,
            }
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(parsed=self.parsed, refusal=None),
                )
            ]
        )

    async def create(self, *, model: str, messages: list[dict[str, str]]) -> object:
        self.create_calls.append({"model": model, "messages": messages})
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.answer))]
        )


class FakeStreamingChatService(FakeChatService):
    def __init__(
        self,
        *,
        streamed_chunks: list[str] | None = None,
        stream_error: Exception | None = None,
        retrieval_query: str | None = None,
        retrieval_broad: bool = False,
    ) -> None:
        super().__init__(
            response_text="unused",
            retrieval_query=retrieval_query,
            retrieval_broad=retrieval_broad,
        )
        self.streamed_chunks = streamed_chunks or []
        self.stream_error = stream_error

    async def stream_answer(
        self,
        *,
        question: str,
        context: str,
        history: list[ChatMessage],
    ) -> AsyncIterator[str]:
        self.history_contents = [message.content for message in history]
        for chunk in self.streamed_chunks:
            yield chunk

        if self.stream_error is not None:
            raise self.stream_error


class ComponentCountingChatService(FakeChatService):
    async def generate_answer(
        self,
        *,
        question: str,
        context: str,
        history: list[ChatMessage],
    ) -> str:
        del question, history
        expected_evidence = (
            "Detected 3 unique components" in context
            and "accordion" in context
            and "alert" in context
            and "avatar" in context
        )
        if expected_evidence:
            return "The document lists three daisyUI components."
        return self.not_supported_token


def _parse_sse_events(response_text: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in response_text.strip().split("\n\n"):
        event_name = ""
        payload: dict[str, object] = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            if line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
        if event_name:
            events.append((event_name, payload))
    return events


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
    app.dependency_overrides[get_settings] = lambda: build_settings()
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


async def _seed_component_document(session_factory: async_sessionmaker[AsyncSession]) -> int:
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
            filename="daisyui.txt",
            content_type="text/plain",
            storage_key="documents/daisyui.txt",
            status=DocumentStatus.ready.value,
            content_hash="daisyui-hash",
        )
        session.add(document)
        await session.flush()
        vector = [1.0] + [0.0] * (EMBEDDING_VECTOR_DIMENSIONS - 1)
        session.add_all(
            [
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=0,
                    text=(
                        "### accordion Accordion is a daisyUI component "
                        "[accordion docs](https://daisyui.com/components/accordion/)"
                    ),
                    snippet="accordion is a daisyUI component.",
                    embedding=vector,
                    token_count=5,
                ),
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=1,
                    text=(
                        "### alert Alert is a daisyUI component "
                        "[alert docs](https://daisyui.com/components/alert/)"
                    ),
                    snippet="alert is a daisyUI component.",
                    embedding=vector,
                    token_count=5,
                ),
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=2,
                    text=(
                        "### avatar Avatar is a daisyUI component "
                        "[avatar docs](https://daisyui.com/components/avatar/)"
                    ),
                    snippet="avatar is a daisyUI component.",
                    embedding=vector,
                    token_count=5,
                ),
            ]
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
async def test_chat_exchange_embeds_model_generated_retrieval_query(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    await _set_chat_services(
        client,
        embedding_service=FakeEmbeddingService({"capital France evidence": [1.0] + [0.0] * 1023}),
        chat_service=FakeChatService(
            "Paris is the capital of France.",
            retrieval_query="capital France evidence",
        ),
    )
    workspace_id = await _seed_ready_document(session_factory)
    chat_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
    )

    response = await client.post(
        "/api/chat/messages",
        json={"session_id": chat_session.id, "message": "What is it?"},
        headers=auth_headers(user_id="user_123"),
    )

    assert response.status_code == 201
    assert response.json()["citations"] == [
        {
            "document_id": 1,
            "document_name": "notes.txt",
            "chunk_id": 1,
            "snippet": "Paris is the capital of France.",
            "page_number": 1,
            "section_label": "Overview",
        }
    ]


@pytest.mark.anyio
async def test_broad_retrieval_plan_uses_expanded_chunk_count(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_settings] = lambda: build_settings(
        retrieval_top_k=1,
        retrieval_expanded_top_k=3,
    )
    await _set_chat_services(
        client,
        embedding_service=FakeEmbeddingService({"daisyUI component list": [1.0] + [0.0] * 1023}),
        chat_service=ComponentCountingChatService(
            "unused",
            retrieval_query="daisyUI component list",
            retrieval_broad=True,
        ),
    )
    workspace_id = await _seed_component_document(session_factory)
    chat_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
    )

    response = await client.post(
        "/api/chat/messages",
        json={"session_id": chat_session.id, "message": "How many components are listed?"},
        headers=auth_headers(user_id="user_123"),
    )

    assert response.status_code == 201
    assert response.json()["grounded"] is True
    assert (
        response.json()["assistant_message"]["content"]
        == "The document lists three daisyUI components."
    )
    assert [item["snippet"] for item in response.json()["citations"]] == [
        "accordion is a daisyUI component.",
        "alert is a daisyUI component.",
        "avatar is a daisyUI component.",
    ]


@pytest.mark.anyio
async def test_structured_retrieval_plan_expands_chunks_through_chat_boundary(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    app = client._transport.app  # type: ignore[attr-defined]
    settings = build_settings(
        enable_structured_retrieval_plan=True,
        retrieval_top_k=1,
        retrieval_expanded_top_k=3,
    )
    chat_api = FakeStructuredChatCompletionsAPI(
        parsed=RetrievalPlanProviderSchema(
            query="daisyUI component list",
            scope="broad",
        ),
        answer="The document lists three daisyUI components.",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.embedding_service = FakeEmbeddingService(
        {"daisyUI component list": [1.0] + [0.0] * 1023}
    )
    app.state.chat_service = ChatService(
        settings,
        client=SimpleNamespace(chat=SimpleNamespace(completions=chat_api)),
    )
    workspace_id = await _seed_component_document(session_factory)
    chat_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
    )

    response = await client.post(
        "/api/chat/messages",
        json={"session_id": chat_session.id, "message": "How many components are listed?"},
        headers=auth_headers(user_id="user_123"),
    )

    assert response.status_code == 201
    assert response.json()["grounded"] is True
    assert (
        response.json()["assistant_message"]["content"]
        == "The document lists three daisyUI components."
    )
    assert [item["snippet"] for item in response.json()["citations"]] == [
        "accordion is a daisyUI component.",
        "alert is a daisyUI component.",
        "avatar is a daisyUI component.",
    ]
    assert chat_api.parse_calls[0]["response_format"] is RetrievalPlanProviderSchema
    assert "Return only compact JSON" not in chat_api.parse_calls[0]["messages"][0]["content"]


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


@pytest.mark.anyio
async def test_stream_chat_message_emits_start_token_done_and_persists_final_answer(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    await _set_chat_services(
        client,
        embedding_service=FakeEmbeddingService(
            {"What is the capital of France?": [1.0] + [0.0] * 1023}
        ),
        chat_service=FakeStreamingChatService(streamed_chunks=["Paris ", "is the capital."]),
    )
    workspace_id = await _seed_ready_document(session_factory)
    chat_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
    )

    response = await client.post(
        "/api/chat/messages/stream",
        json={"session_id": chat_session.id, "message": "What is the capital of France?"},
        headers=auth_headers(user_id="user_123"),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_events(response.text)
    assert [name for name, _ in events] == ["start", "token", "token", "done"]
    assert [payload["text"] for name, payload in events if name == "token"] == [
        "Paris ",
        "is the capital.",
    ]
    assert events[-1][1]["grounded"] is True
    assert events[-1][1]["citations"] == [
        {
            "document_id": 1,
            "document_name": "notes.txt",
            "chunk_id": 1,
            "snippet": "Paris is the capital of France.",
            "page_number": 1,
            "section_label": "Overview",
        }
    ]
    assert events[-1][1]["assistant_message"]["content"] == "Paris is the capital."

    async with session_factory() as session:
        persisted_messages = list(
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == chat_session.id)
                .order_by(ChatMessage.id)
            )
        )

    assert [(item.role, item.content, item.grounded) for item in persisted_messages] == [
        ("user", "What is the capital of France?", False),
        ("assistant", "Paris is the capital.", True),
    ]


@pytest.mark.anyio
async def test_stream_chat_message_streams_abstention_without_citations(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    await _set_chat_services(
        client,
        embedding_service=FakeEmbeddingService({"Unsupported question": [0.0] * 1024}),
        chat_service=FakeStreamingChatService(streamed_chunks=["should not be used"]),
    )
    workspace_id = await _seed_ready_document(session_factory)
    chat_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
    )

    response = await client.post(
        "/api/chat/messages/stream",
        json={"session_id": chat_session.id, "message": "Unsupported question"},
        headers=auth_headers(user_id="user_123"),
    )

    assert response.status_code == 200

    events = _parse_sse_events(response.text)
    assert [name for name, _ in events] == ["start", "token", "done"]
    assert events[1][1]["text"] == "I can’t support an answer to that from the uploaded documents."
    assert events[-1][1]["grounded"] is False
    assert events[-1][1]["citations"] == []
    assert events[-1][1]["assistant_message"]["content"] == events[1][1]["text"]


@pytest.mark.anyio
async def test_stream_chat_message_returns_error_event_and_keeps_partial_answer_out_of_history(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    await _set_chat_services(
        client,
        embedding_service=FakeEmbeddingService(
            {"What is the capital of France?": [1.0] + [0.0] * 1023}
        ),
        chat_service=FakeStreamingChatService(
            streamed_chunks=["Paris "],
            stream_error=RuntimeError("provider stream broke"),
        ),
    )
    workspace_id = await _seed_ready_document(session_factory)
    chat_session = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_123",
    )

    response = await client.post(
        "/api/chat/messages/stream",
        json={"session_id": chat_session.id, "message": "What is the capital of France?"},
        headers=auth_headers(user_id="user_123"),
    )

    assert response.status_code == 200

    events = _parse_sse_events(response.text)
    assert [name for name, _ in events] == ["start", "token", "error"]
    assert events[-1][1] == {"detail": "Chat response stream failed"}

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

    assert [(item.role, item.content) for item in persisted_messages] == [
        ("user", "What is the capital of France?"),
    ]
    assert len(title_jobs) == 1


@pytest.mark.anyio
async def test_stream_chat_message_enforces_auth_and_session_ownership(
    chat_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = chat_harness
    await _set_chat_services(
        client,
        embedding_service=FakeEmbeddingService(
            {"What is the capital of France?": [1.0] + [0.0] * 1023}
        ),
        chat_service=FakeStreamingChatService(streamed_chunks=["Paris"]),
    )
    workspace_id = await _seed_ready_document(session_factory)
    owned_by_other_user = await _create_session(
        session_factory,
        workspace_id=workspace_id,
        clerk_user_id="user_other",
    )

    unauthenticated_response = await client.post(
        "/api/chat/messages/stream",
        json={"session_id": owned_by_other_user.id, "message": "What is the capital of France?"},
    )
    non_owned_response = await client.post(
        "/api/chat/messages/stream",
        json={"session_id": owned_by_other_user.id, "message": "What is the capital of France?"},
        headers=auth_headers(user_id="user_123"),
    )

    assert unauthenticated_response.status_code == 401
    assert unauthenticated_response.json() == {"detail": "authentication required"}
    assert non_owned_response.status_code == 404
    assert non_owned_response.json() == {"detail": "chat session not found"}
