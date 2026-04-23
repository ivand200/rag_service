from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


def get_async_database_url(database_url: str | None = None) -> str:
    url = make_url(database_url or get_settings().database_url)

    if url.drivername in {"sqlite", "sqlite+pysqlite"}:
        return url.set(drivername="sqlite+aiosqlite").render_as_string(hide_password=False)

    return url.render_as_string(hide_password=False)


@lru_cache(maxsize=1)
def get_async_engine() -> AsyncEngine:
    return create_async_engine(
        get_async_database_url(),
        future=True,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        get_async_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_async_session_factory()() as session:
        yield session


async def dispose_async_engine() -> None:
    if get_async_engine.cache_info().currsize == 0:
        return

    engine = get_async_engine()
    get_async_session_factory.cache_clear()
    get_async_engine.cache_clear()
    await engine.dispose()
