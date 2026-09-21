"""LLM client with structured output, retries, and a deterministic fake for tests."""

from __future__ import annotations

import json
import logging
import time
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.core.config import Settings, get_settings
from app.core.errors import ProviderError
from app.core.logging import get_logger, log_event

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class BaseLLM:
    """Interface every LLM provider implements."""

    def structured(
        self, prompt: str, schema: type[T], *, system: str = "", temperature: float | None = None
    ) -> T:
        raise NotImplementedError

    def text(self, prompt: str, *, system: str = "", temperature: float | None = None) -> str:
        raise NotImplementedError


class GeminiLLM(BaseLLM):
    """Google Gemini provider using the google-genai SDK."""

    def __init__(self, settings: Settings):
        from google import genai

        if not settings.google_api_key:
            raise ProviderError("GOOGLE_API_KEY is not configured.")
        self.settings = settings
        self.client = genai.Client(api_key=settings.google_api_key)

    def _config(self, system: str, temperature: float | None, schema: type[T] | None):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=self.settings.llm_temperature if temperature is None else temperature,
            max_output_tokens=self.settings.llm_max_output_tokens,
            response_mime_type="application/json" if schema else None,
            response_schema=schema,
        )

    def _call(self, prompt: str, config) -> str:
        """Call Gemini with bounded exponential backoff."""
        last_error: Exception | None = None
        for attempt in range(1, self.settings.llm_max_retries + 1):
            started = time.perf_counter()
            try:
                response = self.client.models.generate_content(
                    model=self.settings.llm_model, contents=prompt, config=config
                )
                log_event(
                    logger,
                    logging.INFO,
                    "llm_call_ok",
                    model=self.settings.llm_model,
                    attempt=attempt,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                return response.text or ""
            except Exception as exc:  # noqa: BLE001 - provider SDK raises broad errors
                last_error = exc
                log_event(
                    logger, logging.WARNING, "llm_call_failed", attempt=attempt, error=str(exc)
                )
                if attempt < self.settings.llm_max_retries:
                    time.sleep(min(2**attempt, 8))
        raise ProviderError(f"LLM call failed after retries: {last_error}")

    def structured(
        self, prompt: str, schema: type[T], *, system: str = "", temperature: float | None = None
    ) -> T:
        raw = self._call(prompt, self._config(system, temperature, schema))
        try:
            return schema.model_validate_json(raw)
        except PydanticValidationError as exc:
            # Models occasionally wrap JSON in prose or code fences; salvage the object.
            salvaged = _extract_json(raw)
            if salvaged is not None:
                try:
                    return schema.model_validate(salvaged)
                except PydanticValidationError:
                    pass
            raise ProviderError(
                "LLM returned output that did not match the schema.",
                details={"schema": schema.__name__, "error": str(exc)[:400]},
            ) from exc

    def text(self, prompt: str, *, system: str = "", temperature: float | None = None) -> str:
        return self._call(prompt, self._config(system, temperature, None)).strip()


class FakeLLM(BaseLLM):
    """Deterministic provider used by tests, CI, and offline eval runs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.calls: list[tuple[str, str]] = []

    def structured(
        self, prompt: str, schema: type[T], *, system: str = "", temperature: float | None = None
    ) -> T:
        self.calls.append((schema.__name__, prompt[:120]))
        return _fake_instance(schema, prompt)

    def text(self, prompt: str, *, system: str = "", temperature: float | None = None) -> str:
        self.calls.append(("text", prompt[:120]))
        return "Generated draft text for offline testing."


def _extract_json(raw: str) -> dict | list | None:
    """Pull the first JSON object or array out of a noisy model response."""
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _fake_instance(schema: type[T], prompt: str) -> T:
    """Build a schema-valid stub so the whole graph is testable without an API key."""
    from app.schemas.job import JobDescription, SkillRequirement
    from app.schemas.tailor import (
        InterviewQuestion,
        MatchReport,
        ResumeBullet,
        SkillMatch,
    )

    evidence_ids = _fake_evidence_ids(prompt)

    if schema is JobDescription:
        return JobDescription(
            title="AI/ML Engineer",
            company="Test Company",
            seniority="entry",
            responsibilities=["Build RAG pipelines", "Ship LLM features"],
            requirements=[
                SkillRequirement(skill="Python", importance="required", context="Core language"),
                SkillRequirement(skill="RAG", importance="required", context="Retrieval systems"),
            ],
            ats_keywords=["Python", "RAG", "LangGraph", "FastAPI"],
        )
    if schema is MatchReport:
        return MatchReport(
            ats_score=72,
            matched=[SkillMatch(skill="Python", status="strong", evidence_ids=evidence_ids)],
            gaps=[SkillMatch(skill="PyTorch", status="missing", note="No evidence found.")],
            summary="Strong Python and RAG evidence; no deep-learning training experience.",
        )

    origin = getattr(schema, "model_fields", {})
    if "items" in origin:
        inner = schema.model_fields["items"].annotation
        if "ResumeBullet" in str(inner):
            return schema(
                items=[
                    ResumeBullet(
                        text="Built a RAG pipeline in Python serving grounded responses.",
                        target_requirement="RAG",
                        evidence_ids=evidence_ids,
                        keywords=["Python", "RAG"],
                    )
                ]
            )
        if "InterviewQuestion" in str(inner):
            return schema(
                items=[
                    InterviewQuestion(
                        question="Walk me through your RAG pipeline.",
                        why_asked="Tests retrieval design depth.",
                        star_answer="Situation: ... Task: ... Action: ... Result: ...",
                    )
                ]
            )
        return schema(items=[])
    return schema()


def _fake_evidence_ids(prompt: str) -> list[str]:
    """Echo back evidence IDs present in the prompt so grounding checks pass."""
    ids = []
    for token in prompt.replace("[", " ").replace("]", " ").split():
        if token.startswith("ev-") and token not in ids:
            ids.append(token.strip(".,;:"))
    return ids[:3]


def get_llm(settings: Settings | None = None) -> BaseLLM:
    settings = settings or get_settings()
    if settings.llm_provider == "fake":
        return FakeLLM(settings)
    return GeminiLLM(settings)
