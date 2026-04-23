from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.session import dispose_async_engine, get_async_session_factory
from app.services.chat import claim_next_title_job, process_title_job
from app.services.ingestion import claim_next_job, process_job
from app.services.llm import ChatService, EmbeddingService
from app.services.observability import bind_log_context, configure_logging, get_logger, log_event
from app.services.storage import StorageService

logger = get_logger(__name__)


async def run_forever() -> None:
    configure_logging()
    settings = get_settings()
    session_factory = get_async_session_factory()
    storage = StorageService(settings)
    embedding_service = EmbeddingService(settings)
    chat_service = ChatService(settings)
    log_event(
        logger,
        "worker_started",
        poll_interval_seconds=settings.ingestion_poll_interval_seconds,
        max_retries=settings.ingestion_max_retries,
    )

    try:
        while True:
            try:
                ingestion_job_id = await _claim_job(
                    session_factory,
                    lambda db: claim_next_job(db, settings),
                )
                if ingestion_job_id is not None:
                    await _process_claimed_job(
                        session_factory=session_factory,
                        job_id=ingestion_job_id,
                        processor=lambda db, claimed_job_id=ingestion_job_id: process_job(
                            db,
                            claimed_job_id,
                            settings,
                            storage,
                            embedding_service,
                        ),
                        correlation_prefix="job",
                    )
                    continue

                title_job_id = await _claim_job(
                    session_factory,
                    lambda db: claim_next_title_job(db, settings),
                )
                if title_job_id is None:
                    await asyncio.sleep(settings.ingestion_poll_interval_seconds)
                    continue

                await _process_claimed_job(
                    session_factory=session_factory,
                    job_id=title_job_id,
                    processor=lambda db, claimed_job_id=title_job_id: process_title_job(
                        db,
                        claimed_job_id,
                        settings,
                        chat_service,
                    ),
                    correlation_prefix="title-job",
                    job_type="chat_session_title",
                )
            except Exception as exc:
                log_event(logger, "worker_loop_error", error=type(exc).__name__, detail=str(exc))
                await asyncio.sleep(settings.ingestion_poll_interval_seconds)
    finally:
        await dispose_async_engine()


async def _claim_job(
    session_factory: async_sessionmaker[AsyncSession],
    claimer: Callable[..., Awaitable[int | None]],
) -> int | None:
    async with session_factory() as session:
        return await claimer(session)


async def _process_claimed_job(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    job_id: int,
    processor: Callable[..., Awaitable[None]],
    correlation_prefix: str,
    job_type: str = "ingestion",
) -> None:
    with bind_log_context(job_id=job_id, correlation_id=f"{correlation_prefix}-{job_id}"):
        log_event(logger, "worker_job_claimed", job_type=job_type)
        async with session_factory() as session:
            await processor(session)


if __name__ == "__main__":
    asyncio.run(run_forever())
