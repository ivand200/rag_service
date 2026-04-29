from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.chunking import chunk_document
from app.services.document_repository import DocumentRepository
from app.services.llm import EmbeddingService
from app.services.observability import bind_log_context, get_logger, log_event
from app.services.parsers import parse_document_bytes
from app.services.storage import StorageService

logger = get_logger(__name__)


async def claim_next_job(session: AsyncSession, settings: Settings) -> int | None:
    repository = DocumentRepository(session)
    job_id = await repository.claim_next_ingestion_job(settings)
    if job_id is None:
        return None

    job = await repository.get_ingestion_job(job_id)
    document = job and await repository.get_document_for_job(job)
    if job is None or document is None:
        return None
    log_event(
        logger,
        "ingestion_job_claimed",
        document_id=document.id,
        job_id=job_id,
        attempt_count=job.attempt_count,
    )
    return job_id


async def process_job(
    session: AsyncSession,
    job_id: int,
    settings: Settings,
    storage: StorageService,
    embedding_service: EmbeddingService,
) -> None:
    repository = DocumentRepository(session)
    job = await repository.get_ingestion_job(job_id)
    if job is None:
        return

    document = await repository.get_document_for_job(job)
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

            completed = await repository.finalize_ingestion_success(
                document_id=document.id,
                job_id=job.id,
                chunks=chunks,
                embeddings=embeddings,
            )
            if not completed:
                log_event(logger, "ingestion_target_deleted")
                return

            log_event(logger, "ingestion_completed", chunks=len(chunks))
        except Exception as exc:
            updated = await repository.mark_ingestion_failed_or_retry(
                document=document,
                job=job,
                settings=settings,
                exc=exc,
            )
            if not updated:
                log_event(
                    logger,
                    "ingestion_target_deleted",
                    error=str(exc)[:500],
                )
                return
            final_failure = job.attempt_count >= settings.ingestion_max_retries
            summary = str(exc)[:500]
            log_event(
                logger,
                "ingestion_failed",
                document_id=document.id,
                job_id=job.id,
                final_failure=final_failure,
                error=summary,
            )
