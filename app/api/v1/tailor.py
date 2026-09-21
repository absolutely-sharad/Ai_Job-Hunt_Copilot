"""Endpoints for running the tailoring pipeline and reading past runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_copilot_service, require_api_key
from app.core.errors import NotFoundError
from app.db.models import RunRecord
from app.db.session import get_session
from app.schemas.tailor import TailorRequest, TailorResponse
from app.services.copilot import CopilotService

router = APIRouter(tags=["tailor"])


@router.post(
    "/tailor",
    response_model=TailorResponse,
    summary="Tailor resume bullets, cover letter, and interview prep to a job description",
)
async def tailor(
    request: TailorRequest,
    service: CopilotService = Depends(get_copilot_service),
    _: None = Depends(require_api_key),
) -> TailorResponse:
    return service.run(request)


@router.get("/runs", summary="List recent runs")
async def list_runs(
    limit: int = 20,
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> list[dict]:
    records = session.scalars(
        select(RunRecord).order_by(RunRecord.created_at.desc()).limit(min(limit, 100))
    ).all()
    return [
        {
            "run_id": record.id,
            "job_title": record.job_title,
            "company": record.company,
            "ats_score": record.ats_score,
            "latency_ms": record.latency_ms,
            "created_at": record.created_at,
        }
        for record in records
    ]


@router.get("/runs/{run_id}", response_model=TailorResponse, summary="Fetch a stored run")
async def get_run(
    run_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> TailorResponse:
    record = session.get(RunRecord, run_id)
    if record is None:
        raise NotFoundError(f"Run '{run_id}' not found.")
    return TailorResponse.model_validate(record.payload)
