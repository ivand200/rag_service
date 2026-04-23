from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_validate_frontend_origin() -> None:
    settings = Settings(
        dashscope_api_key="test-key",
        frontend_origin="http://localhost:5173/",
    )
    assert settings.frontend_origin == "http://localhost:5173"


def test_settings_default_clerk_authorized_parties_to_frontend_origin() -> None:
    settings = Settings(
        dashscope_api_key="test-key",
        frontend_origin="http://localhost:5173/",
    )

    assert settings.clerk_authorized_parties == ["http://localhost:5173"]


def test_settings_parse_clerk_authorized_parties() -> None:
    settings = Settings(
        dashscope_api_key="test-key",
        clerk_authorized_parties="http://localhost:5173/, https://demo.example.com/",
    )

    assert settings.clerk_authorized_parties == [
        "http://localhost:5173",
        "https://demo.example.com",
    ]


def test_settings_normalize_escaped_clerk_public_key_newlines() -> None:
    settings = Settings(
        dashscope_api_key="test-key",
        clerk_jwt_public_key="-----BEGIN PUBLIC KEY-----\\nabc\\n-----END PUBLIC KEY-----",
    )

    assert (
        settings.clerk_jwt_public_key == "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----"
    )


def test_settings_reject_invalid_clerk_authorized_parties() -> None:
    with pytest.raises(ValueError):
        Settings(
            dashscope_api_key="test-key",
            clerk_authorized_parties="localhost:5173",
        )
