from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Document, DocumentStatus, IngestionJob, JobStatus

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_workspace_documents(self, *, workspace_id: int) -> list[Document]:
        return list(
            await self.session.scalars(
                select(Document).where(Document.workspace_id == workspace_id).order_by(Document.id)
            )
        )

    async def get_document(self, document_id: int) -> Document | None:
        return await self.session.get(Document, document_id)

    async def create_document_with_ingestion_job(
        self,
        *,
        workspace_id: int,
        filename: str,
        content_type: str | None,
        storage_key: str,
        content_hash: str,
    ) -> tuple[Document, IngestionJob]:
        document = Document(
            workspace_id=workspace_id,
            filename=filename,
            content_type=content_type,
            storage_key=storage_key,
            status=DocumentStatus.pending.value,
            content_hash=content_hash,
        )
        self.session.add(document)
        await self.session.flush()

        job = IngestionJob(
            document_id=document.id,
            status=JobStatus.queued.value,
            attempt_count=0,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(document)
        return document, job

    async def claim_next_ingestion_job(self, settings: Settings) -> int | None:
        statement = (
            select(IngestionJob)
            .join(Document)
            .where(IngestionJob.status == JobStatus.queued.value)
            .where(IngestionJob.attempt_count < settings.ingestion_max_retries)
            .order_by(IngestionJob.created_at)
            .limit(1)
        )
        if self.session.bind and self.session.bind.sync_engine.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)

        job = await self.session.scalar(statement)
        if job is None:
            return None

        document = await self.session.get(Document, job.document_id)
        if document is None:
            return None

        now = datetime.now(UTC)
        job.status = JobStatus.processing.value
        job.locked_at = now
        job.attempt_count += 1
        document.status = DocumentStatus.processing.value
        document.error_summary = None
        await self.session.commit()
        return job.id

    async def get_ingestion_job(self, job_id: int) -> IngestionJob | None:
        return await self.session.get(IngestionJob, job_id)

    async def get_document_for_job(self, job: IngestionJob) -> Document | None:
        return await self.session.get(Document, job.document_id)

    async def mark_ingestion_ready(self, *, document: Document, job: IngestionJob) -> None:
        now = datetime.now(UTC)
        document.status = DocumentStatus.ready.value
        document.error_summary = None
        job.status = JobStatus.completed.value
        job.completed_at = now
        job.last_error = None
        job.locked_at = None
        await self.session.commit()

    async def mark_ingestion_failed_or_retry(
        self,
        *,
        document: Document,
        job: IngestionJob,
        settings: Settings,
        exc: Exception,
    ) -> None:
        summary = str(exc)[:500]
        final_failure = job.attempt_count >= settings.ingestion_max_retries

        document.status = (
            DocumentStatus.failed.value if final_failure else DocumentStatus.pending.value
        )
        document.error_summary = summary
        job.status = JobStatus.failed.value if final_failure else JobStatus.queued.value
        job.last_error = summary
        job.locked_at = None
        if final_failure:
            job.completed_at = datetime.now(UTC)

        await self.session.commit()
