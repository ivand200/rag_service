from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_current_user
from app.api.schemas import ChatMessageRead, DocumentSummary, WorkspaceResponse
from app.db.session import get_db_session
from app.services.auth import AuthenticatedUser
from app.services.workspace import (
    ensure_workspace,
    list_workspace_documents,
    list_workspace_messages,
)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("", response_model=WorkspaceResponse)
async def get_workspace(
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    workspace = await ensure_workspace(session)
    documents = await list_workspace_documents(session, workspace.id)
    messages = await list_workspace_messages(
        session,
        workspace.id,
        clerk_user_id=current_user.clerk_user_id,
    )
    document_summaries = [
        DocumentSummary.model_validate(document, from_attributes=True) for document in documents
    ]
    message_summaries = [
        ChatMessageRead.model_validate(message, from_attributes=True) for message in messages
    ]
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        documents=document_summaries,
        messages=message_summaries,
    )
