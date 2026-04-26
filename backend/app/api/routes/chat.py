from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_chat_service, get_embedding_service, require_current_user
from app.api.schemas import (
    ChatExchangeResponse,
    ChatHistoryResponse,
    ChatMessageCreate,
    ChatMessageRead,
    ChatMessageStreamDoneEvent,
    ChatMessageStreamErrorEvent,
    ChatMessageStreamStartEvent,
    ChatMessageStreamTokenEvent,
    ChatSessionRead,
    ChatSessionsResponse,
)
from app.config import Settings, get_settings
from app.db.models import ChatMessage, ChatSession
from app.db.session import get_db_session
from app.services.auth import AuthenticatedUser
from app.services.chat import (
    ChatSessionNotFoundError,
    create_chat_exchange,
    create_chat_session,
    finalize_prepared_chat_exchange,
    list_chat_messages_for_session,
    list_chat_sessions_for_user,
    prepare_chat_exchange,
    stream_prepared_chat_answer,
)
from app.services.llm import ChatService, EmbeddingService
from app.services.observability import bind_log_context, get_logger, log_event

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = get_logger(__name__)


@router.get("/sessions", response_model=ChatSessionsResponse)
async def list_chat_sessions(
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ChatSessionsResponse:
    sessions = await list_chat_sessions_for_user(
        session,
        clerk_user_id=current_user.clerk_user_id,
    )
    return ChatSessionsResponse(sessions=[_to_chat_session(item) for item in sessions])


@router.post("/sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ChatSessionRead:
    chat_session = await create_chat_session(
        session,
        clerk_user_id=current_user.clerk_user_id,
    )
    return _to_chat_session(chat_session)


@router.get("/messages", response_model=ChatHistoryResponse)
async def list_chat_messages(
    session_id: int = Query(..., gt=0),
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ChatHistoryResponse:
    try:
        messages = await list_chat_messages_for_session(
            session,
            clerk_user_id=current_user.clerk_user_id,
            session_id=session_id,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="chat session not found") from exc

    return ChatHistoryResponse(messages=[_to_chat_message(message) for message in messages])


@router.post("/messages", response_model=ChatExchangeResponse, status_code=status.HTTP_201_CREATED)
async def create_chat_message(
    payload: ChatMessageCreate,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatExchangeResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    try:
        result = await create_chat_exchange(
            session=session,
            settings=settings,
            embedding_service=embedding_service,
            chat_service=chat_service,
            message=message,
            clerk_user_id=current_user.clerk_user_id,
            session_id=payload.session_id,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="chat session not found") from exc

    with bind_log_context(
        request_id=getattr(request.state, "request_id", None),
        correlation_id=getattr(request.state, "correlation_id", None),
        workspace_id=result.workspace.id,
        clerk_user_id=current_user.clerk_user_id,
        chat_session_id=result.chat_session.id,
        user_message_id=result.user_message.id,
        assistant_message_id=result.assistant_message.id,
    ):
        log_event(
            logger,
            "chat_message_created",
            grounded=result.grounded,
            citations=len(result.citations),
            top_score=round(result.top_score, 4),
        )

    return ChatExchangeResponse(
        user_message=_to_chat_message(result.user_message),
        assistant_message=_to_chat_message(result.assistant_message),
        citations=result.citations,
        grounded=result.grounded,
    )


@router.post("/messages/stream")
async def create_chat_message_stream(
    payload: ChatMessageCreate,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    chat_service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    try:
        prepared_exchange = await prepare_chat_exchange(
            session=session,
            settings=settings,
            embedding_service=embedding_service,
            chat_service=chat_service,
            message=message,
            clerk_user_id=current_user.clerk_user_id,
            session_id=payload.session_id,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="chat session not found") from exc

    async def event_stream() -> AsyncIterator[str]:
        answer_chunks: list[str] = []

        with bind_log_context(
            request_id=getattr(request.state, "request_id", None),
            correlation_id=getattr(request.state, "correlation_id", None),
            workspace_id=prepared_exchange.workspace.id,
            clerk_user_id=current_user.clerk_user_id,
            chat_session_id=prepared_exchange.chat_session.id,
            user_message_id=prepared_exchange.user_message.id,
        ):
            yield _encode_sse_event(
                "start",
                ChatMessageStreamStartEvent(
                    user_message=_to_chat_message(prepared_exchange.user_message),
                ),
            )

            try:
                async for chunk in stream_prepared_chat_answer(
                    prepared_exchange=prepared_exchange,
                    chat_service=chat_service,
                ):
                    answer_chunks.append(chunk)
                    yield _encode_sse_event(
                        "token",
                        ChatMessageStreamTokenEvent(text=chunk),
                    )

                result = await finalize_prepared_chat_exchange(
                    session=session,
                    prepared_exchange=prepared_exchange,
                    answer="".join(answer_chunks),
                    not_supported_token=chat_service.not_supported_token,
                )
            except Exception as exc:
                log_event(
                    logger,
                    "chat_message_stream_failed",
                    error=type(exc).__name__,
                    detail=str(exc),
                    streamed_chars=sum(len(chunk) for chunk in answer_chunks),
                )
                yield _encode_sse_event(
                    "error",
                    ChatMessageStreamErrorEvent(detail="Chat response stream failed"),
                )
                return

            log_event(
                logger,
                "chat_message_stream_completed",
                grounded=result.grounded,
                citations=len(result.citations),
                top_score=round(result.top_score, 4),
                assistant_message_id=result.assistant_message.id,
                streamed_chars=sum(len(chunk) for chunk in answer_chunks),
            )
            yield _encode_sse_event(
                "done",
                ChatMessageStreamDoneEvent(
                    assistant_message=_to_chat_message(result.assistant_message),
                    citations=result.citations,
                    grounded=result.grounded,
                ),
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _to_chat_message(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead.model_validate(message, from_attributes=True)


def _to_chat_session(chat_session: ChatSession) -> ChatSessionRead:
    return ChatSessionRead.model_validate(chat_session, from_attributes=True)


def _encode_sse_event(event_name: str, payload: BaseModel) -> str:
    body = json.dumps(payload.model_dump(mode="json"), separators=(",", ":"))
    return f"event: {event_name}\ndata: {body}\n\n"
