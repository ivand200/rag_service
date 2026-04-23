from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_storage_service
from app.config import get_settings
from app.db.session import get_db_session
from app.services.storage import StorageService, maybe_await

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name, "environment": settings.app_env}


@router.get("/ready")
async def ready(
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
) -> dict[str, object]:
    settings = get_settings()
    checks = {
        "database": "unknown",
        "object_storage": "unknown",
        "provider_config": "unknown",
    }
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    checks["database"] = "ok"

    if not settings.dashscope_api_key:
        raise HTTPException(status_code=503, detail="provider configuration missing")
    checks["provider_config"] = "ok"

    try:
        await maybe_await(storage.check_bucket_access())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="object storage unavailable") from exc
    checks["object_storage"] = "ok"

    return {"status": "ready", "checks": checks}
