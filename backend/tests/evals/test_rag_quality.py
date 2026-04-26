from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.constants import (
    EMBEDDING_VECTOR_DIMENSIONS,
    SINGLETON_WORKSPACE_ID,
    SINGLETON_WORKSPACE_NAME,
)
from app.db.models import Base, ChatSession, Document, DocumentChunk, DocumentStatus, Workspace
from app.services.chat import (
    ABSTENTION_MESSAGE,
    GROUNDING_MIN_SCORE,
    create_chat_exchange,
)
from app.services.chunking import chunk_document
from app.services.llm import RetrievalPlan
from app.services.parsers import ParsedDocument, ParsedSegment
from app.services.retrieval import search_ready_chunks

CLERK_USER_ID = "user_quality_eval"
FORMAT_QUERY = "What file formats can I upload?"
UNSUPPORTED_QUERY = "Can I upload Excel spreadsheets?"


@dataclass(slots=True)
class SeededCorpus:
    workspace_id: int
    format_chunk_id: int
    pending_chunk_id: int
    session_id: int


class FakeEmbeddingService:
    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [_embedding_for_text(text) for text in texts]


class FakeChatService:
    not_supported_token = "NOT_SUPPORTED"

    async def generate_retrieval_plan(
        self,
        *,
        message: str,
        history: Sequence[object],
    ) -> RetrievalPlan:
        del history
        return RetrievalPlan(query=message, broad=False)

    async def generate_answer(
        self,
        *,
        question: str,
        context: str,
        history: Sequence[object],
    ) -> str:
        del question, history
        if ".txt" in context and ".md" in context and ".pdf" in context:
            return "The supported upload formats are .txt, .md, and .pdf."
        return self.not_supported_token


def build_settings(**overrides: object) -> Settings:
    return Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        database_url="sqlite+pysqlite:///:memory:",
        s3_endpoint_url="http://localhost:9000",
        **overrides,
    )


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

    factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_grounded_question_retrieves_expected_ready_chunk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus = await _seed_corpus(session_factory)

    async with session_factory() as session:
        chunks = await search_ready_chunks(
            session=session,
            workspace_id=corpus.workspace_id,
            query_embedding=_embedding_for_text(FORMAT_QUERY),
            top_k=1,
        )

    assert chunks[0].chunk_id == corpus.format_chunk_id
    assert chunks[0].score >= GROUNDING_MIN_SCORE


@pytest.mark.anyio
async def test_grounded_answer_returns_expected_citation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus = await _seed_corpus(session_factory)

    async with session_factory() as session:
        result = await create_chat_exchange(
            session=session,
            settings=build_settings(retrieval_top_k=2),
            embedding_service=FakeEmbeddingService(),
            chat_service=FakeChatService(),
            message=FORMAT_QUERY,
            clerk_user_id=CLERK_USER_ID,
            session_id=corpus.session_id,
        )

    assert result.grounded is True
    assert result.citations[0].chunk_id == corpus.format_chunk_id


@pytest.mark.anyio
async def test_unsupported_question_abstains_when_top_score_is_below_threshold(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus = await _seed_corpus(session_factory)

    async with session_factory() as session:
        result = await create_chat_exchange(
            session=session,
            settings=build_settings(retrieval_top_k=2),
            embedding_service=FakeEmbeddingService(),
            chat_service=FakeChatService(),
            message=UNSUPPORTED_QUERY,
            clerk_user_id=CLERK_USER_ID,
            session_id=corpus.session_id,
        )

    assert result.top_score < GROUNDING_MIN_SCORE
    assert (result.assistant_message.content, result.citations) == (ABSTENTION_MESSAGE, [])


@pytest.mark.anyio
async def test_non_ready_document_chunks_are_ignored_by_retrieval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus = await _seed_corpus(session_factory)

    async with session_factory() as session:
        chunks = await search_ready_chunks(
            session=session,
            workspace_id=corpus.workspace_id,
            query_embedding=_embedding_for_key("pending-excel"),
            top_k=5,
        )

    assert corpus.pending_chunk_id not in {chunk.chunk_id for chunk in chunks}
    assert {chunk.document_name for chunk in chunks} == {"rag-service-product.md"}


def test_chunk_settings_can_be_compared_with_seeded_document() -> None:
    parsed = ParsedDocument(
        segments=[
            ParsedSegment(
                text=" ".join(f"token-{index}" for index in range(40)),
                page_number=1,
                section_label="Seeded comparison",
            )
        ]
    )

    small_chunks = chunk_document(
        parsed,
        build_settings(chunk_target_tokens=10, chunk_overlap_tokens=2),
    )
    large_chunks = chunk_document(
        parsed,
        build_settings(chunk_target_tokens=20, chunk_overlap_tokens=4),
    )
    current_chunks = chunk_document(
        parsed,
        build_settings(chunk_target_tokens=800, chunk_overlap_tokens=120),
    )

    assert len(small_chunks) > len(large_chunks) > len(current_chunks)
    assert current_chunks[0].section_label == "Seeded comparison"


async def _seed_corpus(
    session_factory: async_sessionmaker[AsyncSession],
) -> SeededCorpus:
    async with session_factory() as session:
        workspace = Workspace(
            id=SINGLETON_WORKSPACE_ID,
            name=SINGLETON_WORKSPACE_NAME,
        )
        session.add(workspace)
        await session.flush()

        ready_document = Document(
            workspace_id=workspace.id,
            filename="rag-service-product.md",
            content_type="text/markdown",
            storage_key="documents/rag-service-product.md",
            status=DocumentStatus.ready.value,
            content_hash="ready-hash",
        )
        pending_document = Document(
            workspace_id=workspace.id,
            filename="future-spreadsheet.md",
            content_type="text/markdown",
            storage_key="documents/future-spreadsheet.md",
            status=DocumentStatus.pending.value,
            content_hash="pending-hash",
        )
        session.add_all([ready_document, pending_document])
        await session.flush()

        format_chunk = DocumentChunk(
            document_id=ready_document.id,
            chunk_index=0,
            text=(
                "Users can upload plain text, Markdown, and PDF source documents. "
                "The accepted file extensions are .txt, .md, and .pdf."
            ),
            snippet="Accepted file extensions are .txt, .md, and .pdf.",
            embedding=_embedding_for_key("formats"),
            token_count=18,
            page_number=1,
            section_label="Supported ingestion formats",
        )
        ready_chunk = DocumentChunk(
            document_id=ready_document.id,
            chunk_index=1,
            text=(
                "A document becomes searchable only after asynchronous ingestion "
                "has completed and the document status is ready."
            ),
            snippet="Documents become searchable after ingestion completes with ready status.",
            embedding=_embedding_for_key("readiness"),
            token_count=16,
            page_number=2,
            section_label="Searchability",
        )
        pending_chunk = DocumentChunk(
            document_id=pending_document.id,
            chunk_index=0,
            text="A future spreadsheet parser may support Excel uploads.",
            snippet="A future spreadsheet parser may support Excel uploads.",
            embedding=_embedding_for_key("pending-excel"),
            token_count=8,
            page_number=1,
            section_label="Pending notes",
        )
        chat_session = ChatSession(
            workspace_id=workspace.id,
            clerk_user_id=CLERK_USER_ID,
            title="New session",
        )
        session.add_all([format_chunk, ready_chunk, pending_chunk, chat_session])
        await session.commit()
        await session.refresh(format_chunk)
        await session.refresh(pending_chunk)
        await session.refresh(chat_session)

        return SeededCorpus(
            workspace_id=workspace.id,
            format_chunk_id=format_chunk.id,
            pending_chunk_id=pending_chunk.id,
            session_id=chat_session.id,
        )


def _embedding_for_text(text: str) -> list[float]:
    normalized = text.casefold()
    if "file formats" in normalized or ".txt" in normalized or ".md" in normalized:
        return _embedding_for_key("formats")
    if "excel" in normalized:
        return _embedding_for_key("unsupported")
    if "ready" in normalized or "searchable" in normalized:
        return _embedding_for_key("readiness")
    return _embedding_for_key("unsupported")


def _embedding_for_key(key: str) -> list[float]:
    indexes = {
        "formats": 0,
        "readiness": 1,
        "pending-excel": 2,
        "unsupported": 50,
    }
    vector = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
    vector[indexes[key]] = 1.0
    return vector
