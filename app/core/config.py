"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Override any field via environment variable."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    app_name: str = "AI Job-Hunt Copilot"
    environment: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    api_key: str | None = Field(
        default=None,
        description="If set, clients must send it as the X-API-Key header.",
    )
    cors_origins: str = "*"

    # --- Providers ---
    llm_provider: Literal["gemini", "fake"] = "gemini"
    google_api_key: str | None = None
    llm_model: str = "gemini-2.0-flash"
    embedding_model: str = "text-embedding-004"
    embedding_dimensions: int = 768
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 4096
    llm_max_retries: int = 3
    llm_timeout_seconds: float = 60.0

    # --- Storage ---
    chroma_path: str = "./data/chroma"
    chroma_collection: str = "profile_chunks"
    database_url: str = "sqlite:///./data/copilot.db"

    # --- Retrieval ---
    chunk_size: int = 900
    chunk_overlap: int = 150
    retrieval_top_k: int = 6
    retrieval_candidate_k: int = 20
    mmr_lambda: float = 0.65
    min_similarity: float = 0.15

    # --- Agent ---
    max_grounding_retries: int = 1
    max_resume_bullets: int = 12

    # --- Rate limiting ---
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
