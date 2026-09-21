"""Liveness and readiness probes."""

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import get_vector_store
from app.core.config import get_settings
from app.db.session import engine

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "llm_provider": settings.llm_provider,
    }


@router.get("/readyz", summary="Readiness probe")
async def readyz(store=Depends(get_vector_store)) -> dict:
    checks = {}
    try:
        checks["vector_store"] = {"ok": True, "chunks": store.count()}
    except Exception as exc:  # noqa: BLE001
        checks["vector_store"] = {"ok": False, "error": str(exc)}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "error": str(exc)}
    ready = all(check["ok"] for check in checks.values())
    return {"status": "ready" if ready else "degraded", "checks": checks}
