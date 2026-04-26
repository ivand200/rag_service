from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db.models import Base
from app.db.session import get_db_session
from app.main import create_app
from app.services.e2e import E2E_BEARER_TOKEN, create_chat_service, create_embedding_service
from tests.api.auth_helpers import TEST_CLERK_PUBLIC_KEY


def build_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "openai_api_key": "test-key",
        "dashscope_api_key": "",
        "database_url": "sqlite+pysqlite:///:memory:",
        "s3_endpoint_url": "http://localhost:9000",
        "clerk_jwt_public_key": TEST_CLERK_PUBLIC_KEY,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def e2e_harness() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    app = create_app(bootstrap_workspace=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_settings] = lambda: build_settings(
        app_env="e2e",
        clerk_jwt_public_key=None,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    await engine.dispose()


@pytest.mark.anyio
async def test_e2e_mode_accepts_fixed_bearer_token(e2e_harness: AsyncClient) -> None:
    response = await e2e_harness.get(
        "/api/workspace",
        headers={"Authorization": f"Bearer {E2E_BEARER_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["messages"] == []


@pytest.mark.anyio
async def test_e2e_mode_still_requires_bearer_token(e2e_harness: AsyncClient) -> None:
    missing_response = await e2e_harness.get("/api/workspace")
    wrong_response = await e2e_harness.get(
        "/api/workspace",
        headers={"Authorization": "Bearer wrong-e2e-token"},
    )

    assert missing_response.status_code == 401
    assert missing_response.json() == {"detail": "authentication required"}
    assert wrong_response.status_code == 401
    assert wrong_response.json() == {"detail": "invalid authentication token"}


@pytest.mark.anyio
async def test_e2e_token_is_ignored_outside_e2e_mode(e2e_harness: AsyncClient) -> None:
    app = e2e_harness._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_settings] = lambda: build_settings(app_env="development")

    response = await e2e_harness.get(
        "/api/workspace",
        headers={"Authorization": f"Bearer {E2E_BEARER_TOKEN}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid authentication token"}


@pytest.mark.anyio
async def test_e2e_services_are_deterministic_without_provider_calls() -> None:
    settings = build_settings(app_env="e2e", clerk_jwt_public_key=None)
    embedding_service = create_embedding_service(settings)
    chat_service = create_chat_service(settings)

    embeddings = await embedding_service.embed_texts(
        [
            "Paris is the capital of France.",
            "What is the capital of France?",
            "What is the moon made of?",
        ]
    )
    answer = await chat_service.generate_answer(
        question="What is the capital of France?",
        context="[Source 1] notes.txt\nParis is the capital of France.",
        history=[],
    )

    assert embeddings[0] == embeddings[1]
    assert embeddings[0] != embeddings[2]
    assert answer == "Paris is the capital of France, based on the uploaded document."
