from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.constants import SINGLETON_WORKSPACE_ID, SINGLETON_WORKSPACE_NAME
from app.db.models import Workspace


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
