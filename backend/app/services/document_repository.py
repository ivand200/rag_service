from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.config import Settings
from app.db.models import Document, DocumentChunk, DocumentStatus, IngestionJob, JobStatus
from app.services.chunking import ChunkCandidate
from app.services.retrieval import replace_document_chunks

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

    async def hard_delete_document(self, *, document_id: int, workspace_id: int) -> str | None:
        storage_key = await self.session.scalar(
            select(Document.storage_key).where(
                Document.id == document_id,
                Document.workspace_id == workspace_id,
            )
        )
        if storage_key is None:
            return None

        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await self.session.execute(
            delete(IngestionJob).where(IngestionJob.document_id == document_id)
        )
        await self.session.execute(
            delete(Document).where(
                Document.id == document_id,
                Document.workspace_id == workspace_id,
            )
        )
        await self.session.commit()
        return storage_key

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

    async def finalize_ingestion_success(
        self,
        *,
        document_id: int,
        job_id: int,
        chunks: Sequence[ChunkCandidate],
        embeddings: Sequence[list[float]],
    ) -> bool:
        target = await self._get_live_ingestion_target(document_id=document_id, job_id=job_id)
        if target is None:
            return False

        document, job = target
        now = datetime.now(UTC)
        try:
            await self.session.run_sync(
                lambda sync_session: replace_document_chunks(
                    sync_session,
                    document,
                    chunks,
                    embeddings,
                )
            )
            document.status = DocumentStatus.ready.value
            document.error_summary = None
            job.status = JobStatus.completed.value
            job.completed_at = now
            job.last_error = None
            job.locked_at = None
            await self.session.commit()
        except (IntegrityError, StaleDataError):
            await self.session.rollback()
            if not await self.ingestion_target_exists(document_id=document_id, job_id=job_id):
                return False
            raise

        return True

    async def mark_ingestion_ready(self, *, document: Document, job: IngestionJob) -> bool:
        target = await self._get_live_ingestion_target(document_id=document.id, job_id=job.id)
        if target is None:
            return False

        live_document, live_job = target
        now = datetime.now(UTC)
        live_document.status = DocumentStatus.ready.value
        live_document.error_summary = None
        live_job.status = JobStatus.completed.value
        live_job.completed_at = now
        live_job.last_error = None
        live_job.locked_at = None
        try:
            await self.session.commit()
        except StaleDataError:
            await self.session.rollback()
            if not await self.ingestion_target_exists(document_id=document.id, job_id=job.id):
                return False
            raise

        return True

    async def mark_ingestion_failed_or_retry(
        self,
        *,
        document: Document,
        job: IngestionJob,
        settings: Settings,
        exc: Exception,
    ) -> bool:
        target = await self._get_live_ingestion_target(document_id=document.id, job_id=job.id)
        if target is None:
            return False

        live_document, live_job = target
        summary = str(exc)[:500]
        final_failure = live_job.attempt_count >= settings.ingestion_max_retries

        live_document.status = (
            DocumentStatus.failed.value if final_failure else DocumentStatus.pending.value
        )
        live_document.error_summary = summary
        live_job.status = JobStatus.failed.value if final_failure else JobStatus.queued.value
        live_job.last_error = summary
        live_job.locked_at = None
        if final_failure:
            live_job.completed_at = datetime.now(UTC)

        try:
            await self.session.commit()
        except StaleDataError:
            await self.session.rollback()
            if not await self.ingestion_target_exists(document_id=document.id, job_id=job.id):
                return False
            raise

        return True

    async def ingestion_target_exists(self, *, document_id: int, job_id: int) -> bool:
        return (
            await self._get_live_ingestion_target(document_id=document_id, job_id=job_id)
        ) is not None

    async def _get_live_ingestion_target(
        self,
        *,
        document_id: int,
        job_id: int,
    ) -> tuple[Document, IngestionJob] | None:
        statement = (
            select(Document, IngestionJob)
            .join(IngestionJob, IngestionJob.document_id == Document.id)
            .where(Document.id == document_id, IngestionJob.id == job_id)
        )
        if self.session.bind and self.session.bind.sync_engine.dialect.name == "postgresql":
            statement = statement.with_for_update()

        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        document, job = row
        return document, job
