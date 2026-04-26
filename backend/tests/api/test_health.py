from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_storage_service
from app.api.routes import health as health_routes
from app.config import Settings
from app.db.models import Base
from app.db.session import get_db_session
from app.main import create_app


class FakeStorage:
    async def check_bucket_access(self) -> None:
        return None


class UnavailableStorage:
    async def check_bucket_access(self) -> None:
        raise RuntimeError("bucket unavailable")


class FailingSession:
    async def execute(self, *args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database unavailable")


def build_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "openai_api_key": "test-key",
        "dashscope_api_key": "",
        "database_url": "sqlite+pysqlite:///:memory:",
        "s3_endpoint_url": "http://localhost:9000",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def health_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[callable]:
    created_engines = []

    async def build_client(
        *,
        settings: Settings | None = None,
        storage: object | None = None,
        db_session: object | None = None,
    ) -> AsyncIterator[AsyncClient]:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        created_engines.append(engine)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        app = create_app(bootstrap_workspace=False)

        async def override_get_db() -> AsyncIterator[object]:
            if db_session is not None:
                yield db_session
                return

            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = override_get_db
        app.dependency_overrides[get_storage_service] = lambda: storage or FakeStorage()
        monkeypatch.setattr(
            health_routes,
            "get_settings",
            lambda: settings or build_settings(),
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client

    try:
        yield build_client
    finally:
        for engine in created_engines:
            await engine.dispose()


@pytest.mark.anyio
async def test_live_reports_service_metadata(
    health_harness,
) -> None:
    async for client in health_harness():
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.headers["x-correlation-id"] == response.headers["x-request-id"]
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "rag-service"


@pytest.mark.anyio
async def test_ready_reports_runtime_checks(
    health_harness,
) -> None:
    async for client in health_harness():
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "ok",
            "object_storage": "ok",
            "provider_config": "ok",
        },
    }


@pytest.mark.anyio
async def test_ready_reports_database_unavailable(
    health_harness,
) -> None:
    async for client in health_harness(db_session=FailingSession()):
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


@pytest.mark.anyio
async def test_ready_reports_provider_configuration_missing(
    health_harness,
) -> None:
    async for client in health_harness(
        settings=build_settings(openai_api_key="", dashscope_api_key="")
    ):
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "provider configuration missing"}


@pytest.mark.anyio
async def test_ready_reports_object_storage_unavailable(
    health_harness,
) -> None:
    async for client in health_harness(storage=UnavailableStorage()):
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "object storage unavailable"}
