"""Gemini client behaviour that matters in production: timeouts and retry policy.

These use a stub client, so they need neither a network connection nor an API key.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.errors import ProviderError
from app.services import llm as llm_module
from app.services.llm import GeminiLLM


class FakeApiError(Exception):
    """Mimics google.genai.errors.APIError, which carries the HTTP status as `.code`."""

    def __init__(self, code: int):
        super().__init__(f"{code} error")
        self.code = code


class StubModels:
    def __init__(self, outcomes: list):
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome

        class Response:
            text = outcome

        return Response()


@pytest.fixture
def make_llm(settings, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(llm_module.time, "sleep", sleeps.append)

    def build(outcomes, **overrides):
        config = settings.model_copy(update={"google_api_key": "test-key", **overrides})
        llm = GeminiLLM(config)  # constructing the SDK client makes no network call
        llm.client = SimpleNamespace(models=StubModels(outcomes))  # SDK `models` is read-only
        return llm, sleeps

    return build


def test_request_timeout_comes_from_settings(settings, monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("google.genai.Client", fake_client)
    GeminiLLM(settings.model_copy(update={"google_api_key": "k", "llm_timeout_seconds": 12.5}))
    assert captured["http_options"].timeout == 12500  # SDK takes milliseconds


def test_permanent_error_is_not_retried(make_llm):
    """A retired model (404) or bad key (401/403) cannot be fixed by waiting."""
    for code in (400, 401, 403, 404):
        llm, sleeps = make_llm([FakeApiError(code)] * 3)
        with pytest.raises(ProviderError, match=str(code)):
            llm.text("hello")
        assert llm.client.models.calls == 1, f"HTTP {code} was retried"
        assert sleeps == []


def test_transient_errors_are_retried_then_surface(make_llm):
    llm, sleeps = make_llm([FakeApiError(503)] * 3, llm_max_retries=3)
    with pytest.raises(ProviderError, match="after retries"):
        llm.text("hello")
    assert llm.client.models.calls == 3
    assert len(sleeps) == 2  # backoff between attempts, none after the last


def test_recovers_from_a_transient_error(make_llm):
    llm, _ = make_llm([FakeApiError(503), "all good"])
    assert llm.text("hello") == "all good"
    assert llm.client.models.calls == 2


def test_rate_limit_is_treated_as_transient(make_llm):
    llm, _ = make_llm([FakeApiError(429), "ok"])
    assert llm.text("hello") == "ok"
