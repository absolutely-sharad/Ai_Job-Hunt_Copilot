"""Endpoints for the job application tracker."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_api_key
from app.core.errors import NotFoundError
from app.db.models import ApplicationRecord, RunRecord
from app.db.session import get_session
from app.schemas.application import (
    APPLIED_STATUSES,
    ApplicationCreate,
    ApplicationOut,
    ApplicationStatus,
    ApplicationUpdate,
)

router = APIRouter(prefix="/applications", tags=["applications"])


def _get_or_404(session: Session, application_id: str) -> ApplicationRecord:
    record = session.get(ApplicationRecord, application_id)
    if record is None:
        raise NotFoundError(f"Application '{application_id}' not found.")
    return record


@router.post(
    "",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Track a job application",
)
async def create_application(
    payload: ApplicationCreate,
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> ApplicationRecord:
    ats_score = None
    if payload.run_id:
        run = session.get(RunRecord, payload.run_id)
        if run is None:
            raise NotFoundError(f"Run '{payload.run_id}' not found.")
        ats_score = run.ats_score

    record = ApplicationRecord(
        id=f"job-{uuid.uuid4().hex[:10]}",
        run_id=payload.run_id,
        job_title=payload.job_title,
        company=payload.company,
        url=payload.url,
        status=payload.status,
        notes=payload.notes,
        ats_score=ats_score,
        applied_at=datetime.now(UTC) if payload.status in APPLIED_STATUSES else None,
    )
    session.add(record)
    session.commit()
    return record


@router.get("", response_model=list[ApplicationOut], summary="List tracked applications")
async def list_applications(
    status_filter: ApplicationStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> list[ApplicationRecord]:
    stmt = select(ApplicationRecord).order_by(ApplicationRecord.updated_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(ApplicationRecord.status == status_filter)
    return list(session.scalars(stmt).all())


@router.get("/{application_id}", response_model=ApplicationOut, summary="Fetch one application")
async def get_application(
    application_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> ApplicationRecord:
    return _get_or_404(session, application_id)


@router.patch("/{application_id}", response_model=ApplicationOut, summary="Update an application")
async def update_application(
    application_id: str,
    payload: ApplicationUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> ApplicationRecord:
    record = _get_or_404(session, application_id)
    changes = payload.model_dump(exclude_unset=True)

    for field in ("job_title", "company", "url", "status", "notes"):
        # An explicit null on a non-nullable column means "leave it", not "erase it".
        if changes.get(field) is not None:
            setattr(record, field, changes[field])
    if "applied_at" in changes:
        record.applied_at = changes["applied_at"]
    elif record.status in APPLIED_STATUSES and record.applied_at is None:
        record.applied_at = datetime.now(UTC)

    session.commit()
    return record


@router.delete(
    "/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Stop tracking an application",
)
async def delete_application(
    application_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> None:
    session.delete(_get_or_404(session, application_id))
    session.commit()
