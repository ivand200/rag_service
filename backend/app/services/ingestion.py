from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Document, DocumentStatus, IngestionJob, JobStatus
from app.services.chunking import chunk_document
from app.services.llm import EmbeddingService
from app.services.observability import bind_log_context, get_logger, log_event
from app.services.parsers import parse_document_bytes
from app.services.retrieval import replace_document_chunks
from app.services.storage import StorageService

logger = get_logger(__name__)

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017


async def claim_next_job(session: AsyncSession, settings: Settings) -> int | None:
    statement = (
        select(IngestionJob)
        .join(Document)
        .where(IngestionJob.status == JobStatus.queued.value)
        .where(IngestionJob.attempt_count < settings.ingestion_max_retries)
        .order_by(IngestionJob.created_at)
        .limit(1)
    )
    if session.bind and session.bind.sync_engine.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)

    job = await session.scalar(statement)
    if job is None:
        return None

    document = await session.get(Document, job.document_id)
    if document is None:
        return None

    now = datetime.now(UTC)
    job.status = JobStatus.processing.value
    job.locked_at = now
    job.attempt_count += 1
    document.status = DocumentStatus.processing.value
    document.error_summary = None
    await session.commit()
    log_event(
        logger,
        "ingestion_job_claimed",
        document_id=document.id,
        job_id=job.id,
        attempt_count=job.attempt_count,
    )
    return job.id


async def process_job(
    session: AsyncSession,
    job_id: int,
    settings: Settings,
    storage: StorageService,
    embedding_service: EmbeddingService,
) -> None:
    job = await session.get(IngestionJob, job_id)
    if job is None:
        return

    document = await session.get(Document, job.document_id)
    if document is None:
        return

    with bind_log_context(
        job_id=job.id,
        document_id=document.id,
        filename=document.filename,
        workspace_id=document.workspace_id,
    ):
        log_event(
            logger,
            "ingestion_started",
            attempt_count=job.attempt_count,
            storage_key=document.storage_key,
        )
        try:
            content = await storage.download_bytes(document.storage_key)
            parsed_document = parse_document_bytes(document.filename, content)
            chunks = chunk_document(parsed_document, settings)

            embeddings: list[list[float]] = []
            for index in range(0, len(chunks), settings.chunk_max_batch_size):
                batch = chunks[index : index + settings.chunk_max_batch_size]
                batch_embeddings = await embedding_service.embed_texts(
                    [chunk.text for chunk in batch]
                )
                embeddings.extend(batch_embeddings)

            await session.run_sync(
                lambda sync_session: replace_document_chunks(
                    sync_session,
                    sync_session.get(Document, document.id),
                    chunks,
                    embeddings,
                )
            )

            now = datetime.now(UTC)
            document.status = DocumentStatus.ready.value
            document.error_summary = None
            job.status = JobStatus.completed.value
            job.completed_at = now
            job.last_error = None
            job.locked_at = None
            await session.commit()
            log_event(logger, "ingestion_completed", chunks=len(chunks))
        except Exception as exc:
            await _handle_ingestion_error(session, document, job, settings, exc)


async def _handle_ingestion_error(
    session: AsyncSession,
    document: Document,
    job: IngestionJob,
    settings: Settings,
    exc: Exception,
) -> None:
    summary = str(exc)[:500]
    final_failure = job.attempt_count >= settings.ingestion_max_retries

    document.status = DocumentStatus.failed.value if final_failure else DocumentStatus.pending.value
    document.error_summary = summary
    job.status = JobStatus.failed.value if final_failure else JobStatus.queued.value
    job.last_error = summary
    job.locked_at = None
    if final_failure:
        job.completed_at = datetime.now(UTC)

    await session.commit()
    log_event(
        logger,
        "ingestion_failed",
        document_id=document.id,
        job_id=job.id,
        final_failure=final_failure,
        error=summary,
    )
