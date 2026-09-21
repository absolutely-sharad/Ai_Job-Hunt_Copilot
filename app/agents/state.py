"""Shared state passed between LangGraph nodes."""

from __future__ import annotations

from typing import Annotated, TypedDict

from app.schemas.job import JobDescription
from app.schemas.profile import EvidenceChunk
from app.schemas.tailor import (
    GroundingViolation,
    InterviewQuestion,
    MatchReport,
    ResumeBullet,
)


def _replace(_: object, new: object) -> object:
    """Last write wins — nodes own distinct slices of state."""
    return new


class CopilotState(TypedDict, total=False):
    # Inputs
    jd_text: str
    tone: str
    include_cover_letter: bool
    include_interview_prep: bool

    # Derived
    job: Annotated[JobDescription, _replace]
    evidence: Annotated[list[EvidenceChunk], _replace]
    match_report: Annotated[MatchReport, _replace]
    resume_bullets: Annotated[list[ResumeBullet], _replace]
    cover_letter: Annotated[str, _replace]
    interview_questions: Annotated[list[InterviewQuestion], _replace]

    # Control
    grounding_violations: Annotated[list[GroundingViolation], _replace]
    grounding_retries: Annotated[int, _replace]
    errors: Annotated[list[str], _replace]
