"""Schemas for the job application tracker."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ApplicationStatus = Literal["saved", "applied", "interviewing", "offer", "rejected", "withdrawn"]

# Moving into one of these stamps `applied_at` if it is not already set.
APPLIED_STATUSES: frozenset[str] = frozenset({"applied", "interviewing", "offer"})


def _check_url(value: str | None) -> str | None:
    """Only http(s) links are stored: the UI renders this value as an <a href>."""
    if value is None:
        return None
    value = value.strip()
    if value and not value.lower().startswith(("http://", "https://")):
        raise ValueError("url must start with http:// or https://")
    return value


class ApplicationCreate(BaseModel):
    job_title: str = Field(min_length=1, max_length=200)
    company: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=1000)
    status: ApplicationStatus = "saved"
    notes: str = Field(default="", max_length=10000)
    run_id: str | None = Field(default=None, description="Tailoring run this application is for.")

    _url = field_validator("url")(_check_url)


class ApplicationUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    job_title: str | None = Field(default=None, min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    status: ApplicationStatus | None = None
    notes: str | None = Field(default=None, max_length=10000)
    applied_at: datetime | None = Field(
        default=None, description="Send null explicitly to clear the applied date."
    )

    _url = field_validator("url")(_check_url)


class ApplicationOut(BaseModel):
    id: str
    run_id: str | None
    job_title: str
    company: str
    url: str
    status: ApplicationStatus
    notes: str
    ats_score: int | None
    applied_at: datetime | None
    created_at: datetime
    updated_at: datetime
