from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_default_to_clerk_auth_mode() -> None:
    settings = Settings(openai_api_key="test-key", dashscope_api_key="")

    assert settings.auth_mode == "clerk"


def test_settings_parse_local_auth_mode_with_local_defaults() -> None:
    settings = Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        auth_mode="local",
    )

    assert settings.auth_mode == "local"
    assert settings.local_dev_user_id == "local-dev-user"
    assert settings.local_dev_session_id == "local-dev-session"


def test_settings_reject_local_auth_mode_in_production() -> None:
    with pytest.raises(ValueError, match="AUTH_MODE=local is not allowed"):
        Settings(
            openai_api_key="test-key",
            dashscope_api_key="",
            app_env="production",
            auth_mode="local",
        )


def test_settings_validate_frontend_origin() -> None:
    settings = Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        frontend_origin="http://localhost:5173/",
    )
    assert settings.frontend_origin == "http://localhost:5173"


def test_settings_default_clerk_authorized_parties_to_frontend_origin() -> None:
    settings = Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        frontend_origin="http://localhost:5173/",
    )

    assert settings.clerk_authorized_parties == ["http://localhost:5173"]


def test_settings_parse_clerk_authorized_parties() -> None:
    settings = Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        clerk_authorized_parties="http://localhost:5173/, https://demo.example.com/",
    )

    assert settings.clerk_authorized_parties == [
        "http://localhost:5173",
        "https://demo.example.com",
    ]


def test_settings_normalize_escaped_clerk_public_key_newlines() -> None:
    settings = Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        clerk_jwt_public_key="-----BEGIN PUBLIC KEY-----\\nabc\\n-----END PUBLIC KEY-----",
    )

    assert (
        settings.clerk_jwt_public_key == "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----"
    )


def test_settings_reject_invalid_clerk_authorized_parties() -> None:
    with pytest.raises(ValueError):
        Settings(
            openai_api_key="test-key",
            dashscope_api_key="",
            clerk_authorized_parties="localhost:5173",
        )


def test_settings_use_openai_provider_configuration_first() -> None:
    settings = Settings(
        openai_api_key="openai-key",
        openai_base_url="https://api.openai.com/v1",
        dashscope_api_key="legacy-key",
        dashscope_base_url="https://dashscope.example.test/v1",
    )

    assert settings.provider_api_key == "openai-key"
    assert settings.provider_base_url == "https://api.openai.com/v1"


def test_settings_allow_legacy_dashscope_provider_configuration() -> None:
    settings = Settings(
        openai_api_key="",
        dashscope_api_key="legacy-key",
        dashscope_base_url="https://dashscope.example.test/v1",
    )

    assert settings.provider_api_key == "legacy-key"
    assert settings.provider_base_url == "https://dashscope.example.test/v1"


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("true", True),
        ("false", False),
    ],
)
def test_settings_parse_structured_retrieval_plan_flag(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("ENABLE_STRUCTURED_RETRIEVAL_PLAN", env_value)

    settings = Settings(openai_api_key="test-key", dashscope_api_key="")

    assert settings.enable_structured_retrieval_plan is expected
