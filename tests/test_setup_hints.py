"""A missing Gemini key must be obvious and self-explaining, not a surprise on first use."""

from __future__ import annotations

import pytest

from app.core.config import ENV_FILES, PROJECT_ROOT
from app.core.errors import ProviderError
from app.services.embeddings import GeminiEmbedder
from app.services.llm import GeminiLLM


@pytest.fixture
def no_key(settings):
    return settings.model_copy(
        update={"llm_provider": "gemini", "google_api_key": None, "environment": "local"}
    )


def _serve(monkeypatch, config):
    monkeypatch.setattr("app.api.v1.health.get_settings", lambda: config)


def test_healthz_is_ready_in_fake_mode(client):
    body = client.get("/healthz").json()
    assert body["llm_ready"] is True
    assert "llm_setup_hint" not in body


def test_healthz_flags_a_missing_key_with_a_local_hint(client, monkeypatch, no_key):
    _serve(monkeypatch, no_key)
    body = client.get("/healthz").json()
    assert body["llm_ready"] is False
    hint = body["llm_setup_hint"]
    assert "GOOGLE_API_KEY" in hint and "LLM_PROVIDER=fake" in hint
    assert str(PROJECT_ROOT / ".env") in hint  # says exactly where it looked
    assert "not found" in hint or "found" in hint


def test_a_set_key_is_ready_and_never_echoed(client, monkeypatch, no_key):
    _serve(monkeypatch, no_key.model_copy(update={"google_api_key": "super-secret-value"}))
    body = client.get("/healthz").json()
    assert body["llm_ready"] is True
    assert "super-secret-value" not in str(body)


def test_deployed_hint_does_not_leak_server_paths(client, monkeypatch, no_key):
    """/healthz is unauthenticated, so outside local mode it must not reveal filesystem paths."""
    _serve(monkeypatch, no_key.model_copy(update={"environment": "production"}))
    hint = client.get("/healthz").json()["llm_setup_hint"]
    assert str(PROJECT_ROOT) not in hint
    assert "environment variable" in hint


def test_project_env_file_is_found_from_any_working_directory():
    first = ENV_FILES[0]
    assert first.is_absolute() and first == PROJECT_ROOT / ".env"
    assert ENV_FILES[-1].name == ".env"  # the current directory still works, and wins


@pytest.mark.parametrize("client_cls", [GeminiLLM, GeminiEmbedder])
def test_missing_key_error_tells_you_how_to_fix_it(no_key, client_cls):
    with pytest.raises(ProviderError) as caught:
        client_cls(no_key)
    message = str(caught.value)
    assert message.startswith("GOOGLE_API_KEY is not configured.")
    assert ".env" in message and "LLM_PROVIDER=fake" in message


def test_app_still_boots_and_warns_when_the_key_is_missing(monkeypatch, no_key, capsys):
    """Startup must survive a missing key (it is the very situation the warning is for)."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setattr("app.main.get_settings", lambda: no_key)
    with TestClient(create_app()) as booted:
        assert booted.get("/healthz").status_code == 200
    out = capsys.readouterr().out
    assert "llm_not_configured" in out and "GOOGLE_API_KEY" in out
