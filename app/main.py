"""FastAPI application factory and entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.core.logging import configure_logging, get_logger, log_event
from app.db.session import init_db

logger = get_logger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
    init_db()
    log_event(
        logger,
        logging.INFO,
        "startup",
        environment=settings.environment,
        llm_provider=settings.llm_provider,
    )
    yield
    log_event(logger, logging.INFO, "shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "RAG + agentic pipeline that tailors resume bullets, cover letters, "
            "and interview prep to a job description, grounded in the candidate's "
            "own indexed experience."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(health.router)
    app.include_router(api_router)

    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
