"""Request and response schemas for the tailoring pipeline."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.job import JobDescription
from app.schemas.profile import EvidenceChunk


class TailorRequest(BaseModel):
    job_description: str = Field(min_length=50, max_length=20000)
    tone: Literal["professional", "concise", "enthusiastic"] = "professional"
    include_cover_letter: bool = True
    include_interview_prep: bool = True


class ResumeBullet(BaseModel):
    """A generated bullet that must cite the evidence it was built from."""

    text: str = Field(description="One ATS-optimised resume bullet.")
    target_requirement: str = Field(description="The JD requirement it answers.")
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="IDs of the profile chunks supporting this bullet.",
    )
    keywords: list[str] = Field(default_factory=list)


class SkillMatch(BaseModel):
    skill: str
    status: Literal["strong", "partial", "missing"]
    evidence_ids: list[str] = Field(default_factory=list)
    note: str = ""


class MatchReport(BaseModel):
    ats_score: int = Field(ge=0, le=100, description="Keyword + evidence coverage.")
    matched: list[SkillMatch] = Field(default_factory=list)
    gaps: list[SkillMatch] = Field(default_factory=list)
    summary: str = ""


class InterviewQuestion(BaseModel):
    question: str
    why_asked: str = ""
    star_answer: str = Field(default="", description="Grounded STAR-format answer.")


class GroundingViolation(BaseModel):
    bullet: str
    reason: str


class TailorResponse(BaseModel):
    run_id: str
    created_at: datetime
    job: JobDescription
    match_report: MatchReport
    resume_bullets: list[ResumeBullet] = Field(default_factory=list)
    cover_letter: str = ""
    interview_questions: list[InterviewQuestion] = Field(default_factory=list)
    evidence: list[EvidenceChunk] = Field(default_factory=list)
    grounding_violations: list[GroundingViolation] = Field(default_factory=list)
    latency_ms: int = 0
