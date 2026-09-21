"""Shared FastAPI dependencies: auth and singleton services."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Header

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.copilot import CopilotService
from app.services.embeddings import get_embedder
from app.services.ingestion import IngestionService
from app.services.vectorstore import VectorStore


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


@lru_cache
def get_vector_store() -> VectorStore:
    return VectorStore(get_settings())


@lru_cache
def get_copilot_service() -> CopilotService:
    return CopilotService(get_settings(), get_vector_store())


@lru_cache
def get_ingestion_service() -> IngestionService:
    settings = get_settings()
    return IngestionService(get_vector_store(), get_embedder(settings), settings)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """No-op when API_KEY is unset (local dev); enforced in deployed environments."""
    settings = get_settings()
    if settings.api_key and x_api_key != settings.api_key:
        raise UnauthorizedError("Missing or invalid X-API-Key header.")
