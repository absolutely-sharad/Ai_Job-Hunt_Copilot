"""Typed application errors mapped to HTTP responses."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for expected, client-visible failures."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class EmptyCorpusError(AppError):
    status_code = 409
    code = "empty_corpus"


class ProviderError(AppError):
    status_code = 502
    code = "provider_error"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request_id_ctx.get(),
            }
        },
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred.",
                "request_id": request_id_ctx.get(),
            }
        },
    )
