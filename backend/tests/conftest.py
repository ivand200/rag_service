from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("VITE_AUTH_MODE", "clerk")
    monkeypatch.setenv("ENABLE_STRUCTURED_RETRIEVAL_PLAN", "false")
