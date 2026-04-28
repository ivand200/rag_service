from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    ChatMessage,
    ChatSession,
    ChatSessionTitleJob,
    JobStatus,
    MessageRole,
    Workspace,
)

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017

DEFAULT_SESSION_TITLE = "New session"


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_sessions_for_user(
        self,
        *,
        workspace_id: int,
        clerk_user_id: str,
    ) -> list[ChatSession]:
        return list(
            await self.session.scalars(
                select(ChatSession)
                .where(
                    ChatSession.workspace_id == workspace_id,
                    ChatSession.clerk_user_id == clerk_user_id,
                )
                .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            )
        )

    async def create_empty_session(
        self,
        *,
        workspace: Workspace,
        clerk_user_id: str,
    ) -> ChatSession:
        chat_session = ChatSession(
            workspace_id=workspace.id,
            clerk_user_id=clerk_user_id,
            title=DEFAULT_SESSION_TITLE,
        )
        self.session.add(chat_session)
        await self.session.commit()
        await self.session.refresh(chat_session)
        return chat_session

    async def find_reusable_empty_session(
        self,
        *,
        workspace_id: int,
        clerk_user_id: str,
    ) -> ChatSession | None:
        latest_session = await self.session.scalar(
            select(ChatSession)
            .where(
                ChatSession.workspace_id == workspace_id,
                ChatSession.clerk_user_id == clerk_user_id,
            )
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            .limit(1)
        )
        if latest_session is None:
            return None
        if await self._session_has_messages(latest_session.id):
            return None
        return latest_session

    async def get_owned_session(
        self,
        *,
        workspace_id: int,
        clerk_user_id: str,
        session_id: int,
    ) -> ChatSession | None:
        return await self.session.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.workspace_id == workspace_id,
                ChatSession.clerk_user_id == clerk_user_id,
            )
        )

    async def list_messages_for_session(
        self,
        *,
        session_id: int,
        clerk_user_id: str,
    ) -> list[ChatMessage]:
        return list(
            await self.session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.clerk_user_id == clerk_user_id,
                )
                .order_by(ChatMessage.id)
            )
        )

    async def list_workspace_messages(
        self,
        *,
        workspace_id: int,
        clerk_user_id: str,
    ) -> list[ChatMessage]:
        return list(
            await self.session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.workspace_id == workspace_id,
                    ChatMessage.clerk_user_id == clerk_user_id,
                )
                .order_by(ChatMessage.id)
            )
        )

    async def get_recent_history(
        self,
        *,
        session_id: int,
        limit: int = 6,
    ) -> Sequence[ChatMessage]:
        messages = list(
            await self.session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.desc())
                .limit(limit)
            )
        )
        messages.reverse()
        return messages

    async def add_user_message(
        self,
        *,
        workspace_id: int,
        clerk_user_id: str,
        session_id: int,
        content: str,
    ) -> ChatMessage:
        message = ChatMessage(
            workspace_id=workspace_id,
            clerk_user_id=clerk_user_id,
            session_id=session_id,
            role=MessageRole.user.value,
            content=content,
            grounded=False,
            citations_json=[],
        )
        self.session.add(message)
        await self.session.flush()
        await self.enqueue_title_job_for_first_user_message(
            chat_session_id=session_id,
        )
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def add_assistant_message_and_touch_session(
        self,
        *,
        workspace_id: int,
        clerk_user_id: str | None,
        chat_session: ChatSession,
        content: str,
        grounded: bool,
        citations_json: list[dict[str, Any]],
    ) -> ChatMessage:
        assistant_message = ChatMessage(
            workspace_id=workspace_id,
            clerk_user_id=clerk_user_id,
            session_id=chat_session.id,
            role=MessageRole.assistant.value,
            content=content,
            grounded=grounded,
            citations_json=citations_json,
        )
        chat_session.updated_at = datetime.now(UTC)
        self.session.add(assistant_message)
        await self.session.commit()
        await self.session.refresh(assistant_message)
        await self.session.refresh(chat_session)
        return assistant_message

    async def enqueue_title_job_for_first_user_message(
        self,
        *,
        chat_session_id: int,
    ) -> None:
        chat_session = await self.session.get(ChatSession, chat_session_id)
        if chat_session is None:
            return
        if chat_session.title != DEFAULT_SESSION_TITLE:
            return

        existing_job = await self.session.scalar(
            select(ChatSessionTitleJob).where(ChatSessionTitleJob.session_id == chat_session.id)
        )
        if existing_job is not None:
            return

        user_message_count = await self.session.scalar(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.session_id == chat_session.id,
                ChatMessage.role == MessageRole.user.value,
            )
        )
        if user_message_count != 1:
            return

        self.session.add(
            ChatSessionTitleJob(
                session_id=chat_session.id,
                status=JobStatus.queued.value,
            )
        )

    async def update_session_title_and_complete_job(
        self,
        *,
        chat_session: ChatSession,
        job: ChatSessionTitleJob,
        title: str,
    ) -> None:
        chat_session.title = title
        chat_session.updated_at = datetime.now(UTC)
        await self.complete_title_job(job)

    async def claim_next_title_job(self, settings: Settings) -> int | None:
        statement = (
            select(ChatSessionTitleJob)
            .where(ChatSessionTitleJob.status == JobStatus.queued.value)
            .where(ChatSessionTitleJob.attempt_count < settings.ingestion_max_retries)
            .order_by(ChatSessionTitleJob.created_at)
            .limit(1)
        )
        if self.session.bind and self.session.bind.sync_engine.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)

        job = await self.session.scalar(statement)
        if job is None:
            return None

        job.status = JobStatus.processing.value
        job.locked_at = datetime.now(UTC)
        job.attempt_count += 1
        await self.session.commit()
        return job.id

    async def get_title_job(self, job_id: int) -> ChatSessionTitleJob | None:
        return await self.session.get(ChatSessionTitleJob, job_id)

    async def get_session(self, session_id: int) -> ChatSession | None:
        return await self.session.get(ChatSession, session_id)

    async def get_session_first_user_message(self, session_id: int) -> str | None:
        return await self.session.scalar(
            select(ChatMessage.content)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.user.value,
            )
            .order_by(ChatMessage.id.asc())
            .limit(1)
        )

    async def complete_title_job(self, job: ChatSessionTitleJob) -> None:
        now = datetime.now(UTC)
        job.status = JobStatus.completed.value
        job.completed_at = now
        job.last_error = None
        job.locked_at = None
        await self.session.commit()

    async def mark_title_job_failed_or_retry(
        self,
        *,
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

        await self.session.commit()

    async def _session_has_messages(self, session_id: int) -> bool:
        message_count = await self.session.scalar(
            select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
        )
        return bool(message_count)
