from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, documents, health, workspace
from app.config import get_settings
from app.db.session import dispose_async_engine, get_async_session_factory
from app.services.observability import (
    configure_logging,
    get_logger,
    log_event,
    request_id_middleware,
)
from app.services.workspace import ensure_workspace

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log_event(logger, "app_startup", bootstrap_workspace=app.state.bootstrap_workspace)
    if app.state.bootstrap_workspace:
        session_factory = get_async_session_factory()
        async with session_factory() as session:
            await ensure_workspace(session)
    try:
        yield
    finally:
        await dispose_async_engine()
        log_event(logger, "app_shutdown")


def create_app(*, bootstrap_workspace: bool = True) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.bootstrap_workspace = bootstrap_workspace
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(request_id_middleware)
    app.include_router(health.router)
    app.include_router(workspace.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    return app


app = create_app()
