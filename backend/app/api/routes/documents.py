from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_storage_service, require_current_user
from app.api.schemas import DocumentDetail, DocumentListResponse, DocumentSummary
from app.config import Settings, get_settings
from app.db.models import Document, DocumentStatus, IngestionJob, JobStatus
from app.db.session import get_db_session
from app.services.auth import AuthenticatedUser
from app.services.observability import bind_log_context, get_logger, log_event
from app.services.storage import StorageService
from app.services.workspace import ensure_workspace, list_workspace_documents

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = get_logger(__name__)
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


def _to_summary(document: Document) -> DocumentSummary:
    return DocumentSummary.model_validate(document, from_attributes=True)


def _to_detail(document: Document) -> DocumentDetail:
    return DocumentDetail.model_validate(document, from_attributes=True)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    _current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentListResponse:
    workspace = await ensure_workspace(session)
    documents = await list_workspace_documents(session, workspace.id)
    return DocumentListResponse(documents=[_to_summary(document) for document in documents])


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: int,
    _current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentDetail:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    return _to_detail(document)


@router.post("", response_model=DocumentSummary, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    _current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage_service),
) -> DocumentSummary:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported file type")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="file is empty")
    if len(content) > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="file exceeds upload limit")

    workspace = await ensure_workspace(session)
    content_hash = sha256(content).hexdigest()
    storage_key = f"documents/{uuid4()}{suffix}"

    await storage.ensure_bucket()
    await storage.upload_bytes(storage_key, content, file.content_type)

    document = Document(
        workspace_id=workspace.id,
        filename=file.filename or f"upload-{datetime.utcnow().isoformat()}{suffix}",
        content_type=file.content_type,
        storage_key=storage_key,
        status=DocumentStatus.pending.value,
        content_hash=content_hash,
    )
    session.add(document)
    await session.flush()

    job = IngestionJob(
        document_id=document.id,
        status=JobStatus.queued.value,
        attempt_count=0,
    )
    session.add(job)
    await session.commit()
    await session.refresh(document)

    with bind_log_context(
        request_id=getattr(getattr(request, "state", None), "request_id", None),
        correlation_id=getattr(getattr(request, "state", None), "correlation_id", None),
        workspace_id=workspace.id,
        document_id=document.id,
        job_id=job.id,
    ):
        log_event(
            logger,
            "document_uploaded",
            filename=document.filename,
            status=document.status,
            bytes=len(content),
            content_type=document.content_type,
        )
    return _to_summary(document)
