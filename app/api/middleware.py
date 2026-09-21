"""Request correlation, access logging, and in-process rate limiting."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.logging import get_logger, log_event, new_request_id, request_id_ctx

logger = get_logger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id to every log line and response header."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        request_id_ctx.set(request_id)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        log_event(
            logger,
            logging.INFO,
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window limiter keyed by client IP.

    In-process by design: one replica on a free tier does not need Redis, and
    the interface is small enough to swap for a shared backend when it does.
    """

    def __init__(self, app):
        super().__init__(app)
        settings = get_settings()
        self.limit = settings.rate_limit_requests
        self.window = settings.rate_limit_window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/healthz", "/readyz") or request.method == "OPTIONS":
            return await call_next(request)

        key = request.client.host if request.client else "unknown"
        now = time.time()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry_after = int(self.window - (now - hits[0])) + 1
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": f"Rate limit of {self.limit} requests per "
                        f"{self.window}s exceeded.",
                        "request_id": request_id_ctx.get(),
                    }
                },
            )
        hits.append(now)
        return await call_next(request)
