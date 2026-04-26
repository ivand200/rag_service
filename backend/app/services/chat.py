from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import Citation
from app.config import Settings
from app.db.models import (
    ChatMessage,
    ChatSession,
    ChatSessionTitleJob,
    JobStatus,
    MessageRole,
    Workspace,
)
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
DEFAULT_SESSION_TITLE = "New session"
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
    sessions = list(
        await session.scalars(
            select(ChatSession)
            .where(
                ChatSession.workspace_id == workspace.id,
                ChatSession.clerk_user_id == clerk_user_id,
            )
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        )
    )
    if sessions:
        return sessions

    created_session = await _create_empty_session(
        session,
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
    existing_empty_session = await _find_reusable_empty_session(
        session,
        workspace=workspace,
        clerk_user_id=clerk_user_id,
    )
    if existing_empty_session is not None:
        return existing_empty_session

    return await _create_empty_session(
        session,
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
    return list(
        await session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == chat_session.id,
                ChatMessage.clerk_user_id == clerk_user_id,
            )
            .order_by(ChatMessage.id)
        )
    )


async def get_owned_chat_session(
    session: AsyncSession,
    *,
    clerk_user_id: str,
    session_id: int,
) -> ChatSession:
    workspace = await ensure_workspace(session)
    chat_session = await session.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.workspace_id == workspace.id,
            ChatSession.clerk_user_id == clerk_user_id,
        )
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
    chat_session = await get_owned_chat_session(
        session,
        clerk_user_id=clerk_user_id,
        session_id=session_id,
    )
    history = await _get_recent_history(session, session_id=chat_session.id)

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

    user_message = ChatMessage(
        workspace_id=workspace.id,
        clerk_user_id=clerk_user_id,
        session_id=chat_session.id,
        role=MessageRole.user.value,
        content=message,
        grounded=False,
        citations_json=[],
    )
    session.add(user_message)
    await session.flush()
    await _enqueue_title_job_for_first_user_message(
        session,
        chat_session=chat_session,
    )
    await session.commit()
    await session.refresh(user_message)

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

    assistant_message = ChatMessage(
        workspace_id=prepared_exchange.workspace.id,
        clerk_user_id=prepared_exchange.user_message.clerk_user_id,
        session_id=prepared_exchange.chat_session.id,
        role=MessageRole.assistant.value,
        content=normalized_answer,
        grounded=grounded,
        citations_json=[citation.model_dump() for citation in citations],
    )
    prepared_exchange.chat_session.updated_at = datetime.now(UTC)
    session.add(assistant_message)
    await session.commit()
    await session.refresh(assistant_message)
    await session.refresh(prepared_exchange.chat_session)

    return ChatExchangeResult(
        workspace=prepared_exchange.workspace,
        chat_session=prepared_exchange.chat_session,
        user_message=prepared_exchange.user_message,
        assistant_message=assistant_message,
        citations=citations,
        grounded=grounded,
        top_score=prepared_exchange.top_score,
    )


async def _get_recent_history(
    session: AsyncSession,
    *,
    session_id: int,
    limit: int = 6,
) -> Sequence[ChatMessage]:
    messages = list(
        await session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
    )
    messages.reverse()
    return messages


async def _create_empty_session(
    session: AsyncSession,
    *,
    workspace: Workspace,
    clerk_user_id: str,
) -> ChatSession:
    chat_session = ChatSession(
        workspace_id=workspace.id,
        clerk_user_id=clerk_user_id,
        title=DEFAULT_SESSION_TITLE,
    )
    session.add(chat_session)
    await session.commit()
    await session.refresh(chat_session)
    return chat_session


async def _find_reusable_empty_session(
    session: AsyncSession,
    *,
    workspace: Workspace,
    clerk_user_id: str,
) -> ChatSession | None:
    latest_session = await session.scalar(
        select(ChatSession)
        .where(
            ChatSession.workspace_id == workspace.id,
            ChatSession.clerk_user_id == clerk_user_id,
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .limit(1)
    )
    if latest_session is None:
        return None
    if await _session_has_messages(session, latest_session.id):
        return None
    return latest_session


async def _session_has_messages(
    session: AsyncSession,
    session_id: int,
) -> bool:
    message_count = await session.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    )
    return bool(message_count)


async def _enqueue_title_job_for_first_user_message(
    session: AsyncSession,
    *,
    chat_session: ChatSession,
) -> None:
    if chat_session.title != DEFAULT_SESSION_TITLE:
        return

    existing_job = await session.scalar(
        select(ChatSessionTitleJob).where(ChatSessionTitleJob.session_id == chat_session.id)
    )
    if existing_job is not None:
        return

    user_message_count = await session.scalar(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.session_id == chat_session.id,
            ChatMessage.role == MessageRole.user.value,
        )
    )
    if user_message_count != 1:
        return

    session.add(
        ChatSessionTitleJob(
            session_id=chat_session.id,
            status=JobStatus.queued.value,
        )
    )


async def claim_next_title_job(session: AsyncSession, settings: Settings) -> int | None:
    statement = (
        select(ChatSessionTitleJob)
        .where(ChatSessionTitleJob.status == JobStatus.queued.value)
        .where(ChatSessionTitleJob.attempt_count < settings.ingestion_max_retries)
        .order_by(ChatSessionTitleJob.created_at)
        .limit(1)
    )
    if session.bind and session.bind.sync_engine.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)

    job = await session.scalar(statement)
    if job is None:
        return None

    now = datetime.now(UTC)
    job.status = JobStatus.processing.value
    job.locked_at = now
    job.attempt_count += 1
    await session.commit()
    return job.id


async def process_title_job(
    session: AsyncSession,
    job_id: int,
    settings: Settings,
    chat_service: ChatService,
) -> None:
    job = await session.get(ChatSessionTitleJob, job_id)
    if job is None:
        return

    chat_session = await session.get(ChatSession, job.session_id)
    if chat_session is None:
        return

    try:
        if chat_session.title != DEFAULT_SESSION_TITLE:
            await _complete_title_job(session, job)
            return

        first_user_message = await session.scalar(
            select(ChatMessage.content)
            .where(
                ChatMessage.session_id == chat_session.id,
                ChatMessage.role == MessageRole.user.value,
            )
            .order_by(ChatMessage.id.asc())
            .limit(1)
        )
        if first_user_message is None:
            await _complete_title_job(session, job)
            return

        generated_title = await chat_service.generate_session_title(
            first_user_message=first_user_message
        )
        normalized_title = _normalize_generated_title(generated_title, first_user_message)
        chat_session.title = normalized_title
        chat_session.updated_at = datetime.now(UTC)
        await _complete_title_job(session, job)
    except Exception as exc:
        await _handle_title_job_error(session, job, settings, exc)


async def _complete_title_job(session: AsyncSession, job: ChatSessionTitleJob) -> None:
    now = datetime.now(UTC)
    job.status = JobStatus.completed.value
    job.completed_at = now
    job.last_error = None
    job.locked_at = None
    await session.commit()


async def _handle_title_job_error(
    session: AsyncSession,
    job: ChatSessionTitleJob,
    settings: Settings,
    exc: Exception,
) -> None:
    summary = str(exc)[:500]
    final_failure = job.attempt_count >= settings.ingestion_max_retries

    job.status = JobStatus.failed.value if final_failure else JobStatus.queued.value
    job.last_error = summary
    job.locked_at = None
    if final_failure:
        job.completed_at = datetime.now(UTC)

    await session.commit()


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
