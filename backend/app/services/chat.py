from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import Citation
from app.config import Settings
from app.db.models import (
    ChatMessage,
    ChatSession,
    Workspace,
)
from app.services.chat_repository import DEFAULT_SESSION_TITLE, ChatRepository
from app.services.llm import ChatService, EmbeddingService, RetrievalPlan, fallback_retrieval_plan
from app.services.observability import get_logger, log_event
from app.services.retrieval import (
    build_broad_grounding_context,
    build_citations,
    build_grounding_context,
    search_ready_chunks,
)
from app.services.workspace import ensure_workspace

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017

GROUNDING_MIN_SCORE = 0.45
ABSTENTION_MESSAGE = "I can’t support an answer to that from the uploaded documents."
MAX_SESSION_TITLE_LENGTH = 255
logger = get_logger(__name__)


class ChatSessionNotFoundError(Exception):
    pass


@dataclass(slots=True)
class ChatExchangePreparation:
    workspace: Workspace
    chat_session: ChatSession
    user_message: ChatMessage
    history: Sequence[ChatMessage]
    question: str
    grounding_context: str
    citations: list[Citation]
    grounded: bool
    top_score: float


@dataclass(slots=True)
class ChatExchangeResult:
    workspace: Workspace
    chat_session: ChatSession
    user_message: ChatMessage
    assistant_message: ChatMessage
    citations: list[Citation]
    grounded: bool
    top_score: float


async def list_chat_sessions_for_user(
    session: AsyncSession,
    *,
    clerk_user_id: str,
) -> list[ChatSession]:
    workspace = await ensure_workspace(session)
    repository = ChatRepository(session)
    sessions = await repository.list_sessions_for_user(
        workspace_id=workspace.id,
        clerk_user_id=clerk_user_id,
    )
    if sessions:
        return sessions

    created_session = await repository.create_empty_session(
        workspace=workspace,
        clerk_user_id=clerk_user_id,
    )
    return [created_session]


async def create_chat_session(
    session: AsyncSession,
    *,
    clerk_user_id: str,
) -> ChatSession:
    workspace = await ensure_workspace(session)
    repository = ChatRepository(session)
    existing_empty_session = await repository.find_reusable_empty_session(
        workspace_id=workspace.id,
        clerk_user_id=clerk_user_id,
    )
    if existing_empty_session is not None:
        return existing_empty_session

    return await repository.create_empty_session(
        workspace=workspace,
        clerk_user_id=clerk_user_id,
    )


async def list_chat_messages_for_session(
    session: AsyncSession,
    *,
    clerk_user_id: str,
    session_id: int,
) -> list[ChatMessage]:
    chat_session = await get_owned_chat_session(
        session,
        clerk_user_id=clerk_user_id,
        session_id=session_id,
    )
    repository = ChatRepository(session)
    return await repository.list_messages_for_session(
        session_id=chat_session.id,
        clerk_user_id=clerk_user_id,
    )


async def get_owned_chat_session(
    session: AsyncSession,
    *,
    clerk_user_id: str,
    session_id: int,
) -> ChatSession:
    workspace = await ensure_workspace(session)
    repository = ChatRepository(session)
    chat_session = await repository.get_owned_session(
        workspace_id=workspace.id,
        clerk_user_id=clerk_user_id,
        session_id=session_id,
    )
    if chat_session is None:
        raise ChatSessionNotFoundError
    return chat_session


async def create_chat_exchange(
    *,
    session: AsyncSession,
    settings: Settings,
    embedding_service: EmbeddingService,
    chat_service: ChatService,
    message: str,
    clerk_user_id: str,
    session_id: int,
) -> ChatExchangeResult:
    prepared_exchange = await prepare_chat_exchange(
        session=session,
        settings=settings,
        embedding_service=embedding_service,
        chat_service=chat_service,
        message=message,
        clerk_user_id=clerk_user_id,
        session_id=session_id,
    )
    answer = ABSTENTION_MESSAGE
    if prepared_exchange.grounded:
        answer = await chat_service.generate_answer(
            question=prepared_exchange.question,
            context=prepared_exchange.grounding_context,
            history=prepared_exchange.history,
        )

    return await finalize_prepared_chat_exchange(
        session=session,
        prepared_exchange=prepared_exchange,
        answer=answer,
        not_supported_token=chat_service.not_supported_token,
    )


async def prepare_chat_exchange(
    *,
    session: AsyncSession,
    settings: Settings,
    embedding_service: EmbeddingService,
    chat_service: ChatService,
    message: str,
    clerk_user_id: str,
    session_id: int,
) -> ChatExchangePreparation:
    workspace = await ensure_workspace(session)
    repository = ChatRepository(session)
    chat_session = await get_owned_chat_session(
        session,
        clerk_user_id=clerk_user_id,
        session_id=session_id,
    )
    history = await repository.get_recent_history(session_id=chat_session.id)

    retrieval_plan = await _build_retrieval_plan(
        chat_service=chat_service,
        message=message,
        history=history,
    )
    query_embedding = (await embedding_service.embed_texts([retrieval_plan.query]))[0]
    retrieval_top_k = (
        max(settings.retrieval_top_k, settings.retrieval_expanded_top_k)
        if retrieval_plan.broad
        else settings.retrieval_top_k
    )
    retrieved_chunks = await search_ready_chunks(
        session=session,
        workspace_id=workspace.id,
        query_embedding=query_embedding,
        top_k=retrieval_top_k,
    )
    top_score = retrieved_chunks[0].score if retrieved_chunks else 0.0

    grounded = bool(retrieved_chunks) and top_score >= GROUNDING_MIN_SCORE
    citations = build_citations(retrieved_chunks) if grounded else []
    if grounded and retrieval_plan.broad:
        grounding_context = build_broad_grounding_context(retrieved_chunks)
    elif grounded:
        grounding_context = build_grounding_context(retrieved_chunks)
    else:
        grounding_context = ""

    user_message = await repository.add_user_message(
        workspace_id=workspace.id,
        clerk_user_id=clerk_user_id,
        session_id=chat_session.id,
        content=message,
    )

    return ChatExchangePreparation(
        workspace=workspace,
        chat_session=chat_session,
        user_message=user_message,
        history=history,
        question=message,
        grounding_context=grounding_context,
        citations=citations,
        grounded=grounded,
        top_score=top_score,
    )


async def _build_retrieval_plan(
    *,
    chat_service: ChatService,
    message: str,
    history: Sequence[ChatMessage],
) -> RetrievalPlan:
    try:
        return await chat_service.generate_retrieval_plan(message=message, history=history)
    except Exception as exc:
        log_event(
            logger,
            "retrieval_plan_failed",
            error=type(exc).__name__,
            detail=str(exc),
        )
        return fallback_retrieval_plan(message)


async def stream_prepared_chat_answer(
    *,
    prepared_exchange: ChatExchangePreparation,
    chat_service: ChatService,
) -> AsyncIterator[str]:
    if not prepared_exchange.grounded:
        yield ABSTENTION_MESSAGE
        return

    async for chunk in chat_service.stream_answer(
        question=prepared_exchange.question,
        context=prepared_exchange.grounding_context,
        history=prepared_exchange.history,
    ):
        if chunk:
            yield chunk


async def finalize_prepared_chat_exchange(
    *,
    session: AsyncSession,
    prepared_exchange: ChatExchangePreparation,
    answer: str,
    not_supported_token: str,
) -> ChatExchangeResult:
    normalized_answer, grounded, citations = _normalize_assistant_answer(
        answer=answer,
        grounded=prepared_exchange.grounded,
        citations=prepared_exchange.citations,
        not_supported_token=not_supported_token,
    )

    assistant_message = await ChatRepository(session).add_assistant_message_and_touch_session(
        workspace_id=prepared_exchange.workspace.id,
        clerk_user_id=prepared_exchange.user_message.clerk_user_id,
        chat_session=prepared_exchange.chat_session,
        content=normalized_answer,
        grounded=grounded,
        citations_json=[citation.model_dump() for citation in citations],
    )

    return ChatExchangeResult(
        workspace=prepared_exchange.workspace,
        chat_session=prepared_exchange.chat_session,
        user_message=prepared_exchange.user_message,
        assistant_message=assistant_message,
        citations=citations,
        grounded=grounded,
        top_score=prepared_exchange.top_score,
    )


async def claim_next_title_job(session: AsyncSession, settings: Settings) -> int | None:
    return await ChatRepository(session).claim_next_title_job(settings)


async def process_title_job(
    session: AsyncSession,
    job_id: int,
    settings: Settings,
    chat_service: ChatService,
) -> None:
    repository = ChatRepository(session)
    job = await repository.get_title_job(job_id)
    if job is None:
        return

    chat_session = await repository.get_session(job.session_id)
    if chat_session is None:
        return

    try:
        if chat_session.title != DEFAULT_SESSION_TITLE:
            await repository.complete_title_job(job)
            return

        first_user_message = await repository.get_session_first_user_message(chat_session.id)
        if first_user_message is None:
            await repository.complete_title_job(job)
            return

        generated_title = await chat_service.generate_session_title(
            first_user_message=first_user_message
        )
        normalized_title = _normalize_generated_title(generated_title, first_user_message)
        await repository.update_session_title_and_complete_job(
            chat_session=chat_session,
            job=job,
            title=normalized_title,
        )
    except Exception as exc:
        await repository.mark_title_job_failed_or_retry(job=job, settings=settings, exc=exc)


def _normalize_assistant_answer(
    *,
    answer: str,
    grounded: bool,
    citations: list[Citation],
    not_supported_token: str,
) -> tuple[str, bool, list[Citation]]:
    normalized_answer = answer.strip()
    if normalized_answer and normalized_answer != not_supported_token:
        return normalized_answer, grounded, citations

    return ABSTENTION_MESSAGE, False, []


def _normalize_generated_title(generated_title: str, fallback_message: str) -> str:
    collapsed = " ".join(generated_title.replace("\n", " ").split()).strip(" \"'.,:;!-")
    if not collapsed:
        collapsed = " ".join(fallback_message.split())

    if not collapsed:
        return DEFAULT_SESSION_TITLE

    return collapsed[:MAX_SESSION_TITLE_LENGTH]
