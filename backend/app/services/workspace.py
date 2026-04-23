from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.constants import SINGLETON_WORKSPACE_ID, SINGLETON_WORKSPACE_NAME
from app.db.models import ChatMessage, Document, Workspace


async def ensure_workspace(session: AsyncSession) -> Workspace:
    workspace = await session.get(Workspace, SINGLETON_WORKSPACE_ID)
    if workspace is not None:
        return workspace

    workspace = Workspace(
        id=SINGLETON_WORKSPACE_ID,
        name=SINGLETON_WORKSPACE_NAME,
    )
    session.add(workspace)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        workspace = await session.get(Workspace, SINGLETON_WORKSPACE_ID)
        if workspace is None:
            raise
        return workspace

    await session.refresh(workspace)
    return workspace


async def list_workspace_documents(
    session: AsyncSession,
    workspace_id: int,
) -> list[Document]:
    return list(
        await session.scalars(
            select(Document).where(Document.workspace_id == workspace_id).order_by(Document.id)
        )
    )


async def list_workspace_messages(
    session: AsyncSession,
    workspace_id: int,
    *,
    clerk_user_id: str,
) -> list[ChatMessage]:
    return list(
        await session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.workspace_id == workspace_id,
                ChatMessage.clerk_user_id == clerk_user_id,
            )
            .order_by(ChatMessage.id)
        )
    )
