"""Embedding client with a deterministic offline fallback."""

from __future__ import annotations

import hashlib
import math

from app.core.config import Settings, get_settings
from app.core.errors import ProviderError


class BaseEmbedder:
    dimensions: int

    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        raise NotImplementedError


class GeminiEmbedder(BaseEmbedder):
    """Gemini text-embedding model with task-type optimisation."""

    def __init__(self, settings: Settings):
        from google import genai

        if not settings.google_api_key:
            raise ProviderError("GOOGLE_API_KEY is not configured.")
        self.settings = settings
        self.dimensions = settings.embedding_dimensions
        self.client = genai.Client(api_key=settings.google_api_key)

    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        from google.genai import types

        if not texts:
            return []
        config = types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT",
            output_dimensionality=self.dimensions,
        )
        try:
            response = self.client.models.embed_content(
                model=self.settings.embedding_model, contents=texts, config=config
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Embedding call failed: {exc}") from exc
        return [list(item.values) for item in response.embeddings]


class FakeEmbedder(BaseEmbedder):
    """Hash-based embeddings: deterministic, offline, and lexically sensitive.

    Not semantically meaningful, but stable enough that retrieval tests assert
    real ranking behaviour instead of mocking the vector store away.
    """

    def __init__(self, settings: Settings):
        self.dimensions = min(settings.embedding_dimensions, 128)

    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def get_embedder(settings: Settings | None = None) -> BaseEmbedder:
    settings = settings or get_settings()
    if settings.llm_provider == "fake":
        return FakeEmbedder(settings)
    return GeminiEmbedder(settings)
