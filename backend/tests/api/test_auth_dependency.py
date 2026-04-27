from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import require_current_user
from app.config import Settings, get_settings
from app.services.auth import AuthenticatedUser
from tests.api.auth_helpers import TEST_CLERK_PUBLIC_KEY


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
async def auth_probe_client() -> AsyncClient:
    app = FastAPI()

    @app.get("/auth-probe")
    async def auth_probe(
        current_user: AuthenticatedUser = Depends(require_current_user),
    ) -> dict[str, str | None]:
        return {
            "clerk_user_id": current_user.clerk_user_id,
            "session_id": current_user.session_id,
        }

    app.dependency_overrides[get_settings] = lambda: build_settings(
        auth_mode="local",
        local_dev_user_id="local-user",
        local_dev_session_id="local-session",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.anyio
async def test_local_auth_mode_returns_configured_synthetic_user_without_bearer(
    auth_probe_client: AsyncClient,
) -> None:
    response = await auth_probe_client.get("/auth-probe")

    assert response.status_code == 200
    assert response.json() == {
        "clerk_user_id": "local-user",
        "session_id": "local-session",
    }
