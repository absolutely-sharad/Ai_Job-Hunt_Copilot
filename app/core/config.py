"""Application configuration loaded from environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Vercel functions run on a read-only filesystem with only /tmp writable (and ephemeral).
ON_VERCEL = bool(os.environ.get("VERCEL"))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# The project's own .env is always found, wherever the server is started from; a .env in the
# current directory (listed last) overrides it. Real environment variables beat both.
ENV_FILES = (PROJECT_ROOT / ".env", Path(".env"))


class Settings(BaseSettings):
    """Runtime settings. Override any field via environment variable."""

    model_config = SettingsConfigDict(env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore")

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
    llm_model: str = "gemini-flash-lite-latest"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 4096
    llm_max_retries: int = 3
    llm_timeout_seconds: float = 60.0

    # --- Storage ---
    # "chroma" = embedded ChromaDB (needs a persistent disk: Docker/Render).
    # "sql"    = vectors stored in the app database (serverless-friendly, use Postgres).
    vector_store: Literal["chroma", "sql"] = "sql" if ON_VERCEL else "chroma"
    chroma_path: str = "/tmp/chroma" if ON_VERCEL else "./data/chroma"
    chroma_collection: str = "profile_chunks"
    database_url: str = "sqlite:////tmp/copilot.db" if ON_VERCEL else "sqlite:///./data/copilot.db"

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
    def llm_ready(self) -> bool:
        """False when the configured provider cannot work yet (Gemini without a key)."""
        return self.llm_provider == "fake" or bool(self.google_api_key)

    @property
    def llm_setup_hint(self) -> str:
        """How to fix a missing key. Includes file paths only in local mode: /healthz is public."""
        fix = (
            "Put GOOGLE_API_KEY=<your key> in a .env file and restart the server, "
            "or set LLM_PROVIDER=fake for demo mode."
        )
        if self.environment != "local":
            return "Set the GOOGLE_API_KEY environment variable for this deployment and redeploy."
        looked = dict.fromkeys(Path(env_file).resolve() for env_file in ENV_FILES)  # de-duplicated
        found = ", ".join(f"{p} ({'found' if p.exists() else 'not found'})" for p in looked)
        return f"{fix} The server looked for: {found}."

    @property
    def sqlalchemy_url(self) -> str:
        """Normalize provider URLs (Neon/Supabase/Vercel Postgres) to the psycopg3 driver."""
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
