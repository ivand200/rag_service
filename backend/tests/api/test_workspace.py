from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db.models import Base, ChatMessage, Workspace
from app.db.session import get_db_session
from app.main import create_app
from tests.api.auth_helpers import TEST_CLERK_PUBLIC_KEY, auth_headers


def build_settings(**overrides: object) -> Settings:
    return Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        database_url="sqlite+pysqlite:///:memory:",
        s3_endpoint_url="http://localhost:9000",
        clerk_jwt_public_key=TEST_CLERK_PUBLIC_KEY,
        **overrides,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def workspace_harness() -> AsyncIterator[
    tuple[AsyncClient, async_sessionmaker[AsyncSession]]
]:
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
    app.dependency_overrides[get_settings] = lambda: build_settings()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client, session_factory

    await engine.dispose()


@pytest.mark.anyio
async def test_workspace_bootstraps_single_workspace(
    workspace_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = workspace_harness

    response = await client.get("/api/workspace", headers=auth_headers())

    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "name": "Personal Workspace",
        "documents": [],
        "messages": [],
    }


@pytest.mark.anyio
async def test_workspace_requires_authentication(
    workspace_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = workspace_harness

    response = await client.get("/api/workspace")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


@pytest.mark.anyio
async def test_workspace_allows_missing_bearer_in_local_auth_mode(
    workspace_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = workspace_harness
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_settings] = lambda: build_settings(
        auth_mode="local",
        local_dev_user_id="local-user",
        local_dev_session_id="local-session",
    )

    async with session_factory() as session:
        workspace = Workspace(name="Personal Workspace")
        session.add(workspace)
        await session.flush()
        session.add_all(
            [
                ChatMessage(
                    workspace_id=workspace.id,
                    clerk_user_id="local-user",
                    role="assistant",
                    content="Visible local answer",
                    grounded=True,
                    citations_json=[],
                ),
                ChatMessage(
                    workspace_id=workspace.id,
                    clerk_user_id="other-user",
                    role="assistant",
                    content="Hidden other answer",
                    grounded=True,
                    citations_json=[],
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/workspace")

    assert response.status_code == 200
    assert [message["content"] for message in response.json()["messages"]] == [
        "Visible local answer"
    ]


@pytest.mark.anyio
async def test_workspace_rejects_invalid_bearer_token(
    workspace_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = workspace_harness

    response = await client.get(
        "/api/workspace",
        headers={"Authorization": "Bearer definitely-not-a-jwt"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid authentication token"}


@pytest.mark.anyio
async def test_workspace_returns_only_current_user_messages(
    workspace_harness: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = workspace_harness

    async with session_factory() as session:
        workspace = Workspace(name="Personal Workspace")
        session.add(workspace)
        await session.flush()
        session.add_all(
            [
                ChatMessage(
                    workspace_id=workspace.id,
                    clerk_user_id="user_123",
                    role="assistant",
                    content="Visible answer",
                    grounded=True,
                    citations_json=[],
                ),
                ChatMessage(
                    workspace_id=workspace.id,
                    clerk_user_id="user_other",
                    role="assistant",
                    content="Hidden other answer",
                    grounded=True,
                    citations_json=[],
                ),
                ChatMessage(
                    workspace_id=workspace.id,
                    clerk_user_id=None,
                    role="assistant",
                    content="Hidden legacy answer",
                    grounded=True,
                    citations_json=[],
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/workspace", headers=auth_headers(user_id="user_123"))

    assert response.status_code == 200
    assert [message["content"] for message in response.json()["messages"]] == ["Visible answer"]
