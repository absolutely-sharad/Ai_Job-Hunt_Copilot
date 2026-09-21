"""LangGraph nodes. Each node owns one step of the tailoring pipeline."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.agents import prompts
from app.agents.state import CopilotState
from app.core.config import Settings
from app.core.errors import EmptyCorpusError
from app.core.logging import get_logger, log_event
from app.schemas.job import JobDescription
from app.schemas.profile import EvidenceChunk
from app.schemas.tailor import (
    GroundingViolation,
    InterviewQuestion,
    MatchReport,
    ResumeBullet,
)
from app.services.llm import BaseLLM
from app.services.retrieval import RetrievalService

logger = get_logger(__name__)


class ResumeBulletList(BaseModel):
    """Wrapper: Gemini structured output requires an object at the root."""

    items: list[ResumeBullet] = Field(default_factory=list)


class InterviewQuestionList(BaseModel):
    items: list[InterviewQuestion] = Field(default_factory=list)


def format_evidence(evidence: list[EvidenceChunk], limit: int = 24) -> str:
    return "\n".join(
        f"[{chunk.id}] :: ({chunk.document_title}) {chunk.text}" for chunk in evidence[:limit]
    )


class CopilotNodes:
    """Node implementations bound to their dependencies."""

    def __init__(self, llm: BaseLLM, retrieval: RetrievalService, settings: Settings):
        self.llm = llm
        self.retrieval = retrieval
        self.settings = settings

    # --- 1. Parse ---------------------------------------------------------
    def parse_jd(self, state: CopilotState) -> CopilotState:
        job = self.llm.structured(
            prompts.PARSE_JD_USER.format(jd_text=state["jd_text"][:15000]),
            JobDescription,
            system=prompts.PARSE_JD_SYSTEM,
        )
        log_event(
            logger, logging.INFO, "jd_parsed", title=job.title, requirements=len(job.requirements)
        )
        return {"job": job}

    # --- 2. Retrieve ------------------------------------------------------
    def retrieve_evidence(self, state: CopilotState) -> CopilotState:
        evidence = self.retrieval.retrieve_for_job(state["job"])
        if not evidence:
            raise EmptyCorpusError(
                "No profile evidence found. Upload your resume and projects before tailoring."
            )
        return {"evidence": evidence}

    # --- 3. Analyse -------------------------------------------------------
    def analyze_match(self, state: CopilotState) -> CopilotState:
        job = state["job"]
        report = self.llm.structured(
            prompts.MATCH_USER.format(
                title=job.title,
                company=job.company,
                seniority=job.seniority,
                requirements="\n".join(
                    f"- {r.skill} ({r.importance}): {r.context}" for r in job.requirements
                ),
                evidence=format_evidence(state["evidence"]),
            ),
            MatchReport,
            system=prompts.MATCH_SYSTEM,
        )
        log_event(logger, logging.INFO, "match_analyzed", ats_score=report.ats_score)
        return {"match_report": report}

    # --- 4. Draft resume --------------------------------------------------
    def draft_resume(self, state: CopilotState) -> CopilotState:
        job = state["job"]
        violations = state.get("grounding_violations") or []
        feedback = (
            prompts.GROUNDING_FEEDBACK.format(
                violations="\n".join(f"- {v.bullet}: {v.reason}" for v in violations)
            )
            if violations
            else ""
        )
        result = self.llm.structured(
            prompts.RESUME_USER.format(
                title=job.title,
                company=job.company,
                keywords=", ".join(job.ats_keywords),
                tone=state.get("tone", "professional"),
                evidence=format_evidence(state["evidence"]),
                max_bullets=self.settings.max_resume_bullets,
                feedback=feedback,
            ),
            ResumeBulletList,
            system=prompts.RESUME_SYSTEM,
        )
        return {"resume_bullets": result.items}

    # --- 5. Grounding critic ---------------------------------------------
    def verify_grounding(self, state: CopilotState) -> CopilotState:
        """Reject bullets whose citations do not exist in the retrieved evidence.

        This is a deterministic check, not an LLM judgement: a bullet either
        cites a real chunk id or it does not.
        """
        valid_ids = {chunk.id for chunk in state["evidence"]}
        kept: list[ResumeBullet] = []
        violations: list[GroundingViolation] = []
        for bullet in state.get("resume_bullets", []):
            cited = [eid for eid in bullet.evidence_ids if eid in valid_ids]
            if not cited:
                violations.append(
                    GroundingViolation(
                        bullet=bullet.text,
                        reason="No valid evidence id cited; bullet is unverifiable.",
                    )
                )
                continue
            bullet.evidence_ids = cited
            kept.append(bullet)
        log_event(
            logger,
            logging.INFO,
            "grounding_checked",
            kept=len(kept),
            violations=len(violations),
        )
        return {
            "resume_bullets": kept,
            "grounding_violations": violations,
            "grounding_retries": state.get("grounding_retries", 0) + 1,
        }

    def should_retry(self, state: CopilotState) -> str:
        """Route back to drafting once if the critic rejected everything."""
        violations = state.get("grounding_violations", [])
        retries = state.get("grounding_retries", 0)
        exhausted = retries > self.settings.max_grounding_retries
        everything_rejected = bool(violations) and not state.get("resume_bullets")
        return "retry" if everything_rejected and not exhausted else "continue"

    # --- 6. Cover letter --------------------------------------------------
    def draft_cover_letter(self, state: CopilotState) -> CopilotState:
        if not state.get("include_cover_letter", True):
            return {"cover_letter": ""}
        job = state["job"]
        report = state["match_report"]
        letter = self.llm.text(
            prompts.COVER_LETTER_USER.format(
                title=job.title,
                company=job.company,
                tone=state.get("tone", "professional"),
                evidence=format_evidence(state["evidence"], limit=10),
                gaps=", ".join(gap.skill for gap in report.gaps) or "none identified",
            ),
            system=prompts.COVER_LETTER_SYSTEM,
        )
        return {"cover_letter": letter}

    # --- 7. Interview prep ------------------------------------------------
    def build_interview_prep(self, state: CopilotState) -> CopilotState:
        if not state.get("include_interview_prep", True):
            return {"interview_questions": []}
        job = state["job"]
        report = state["match_report"]
        result = self.llm.structured(
            prompts.INTERVIEW_USER.format(
                title=job.title,
                company=job.company,
                requirements=", ".join(r.skill for r in job.requirements),
                gaps=", ".join(gap.skill for gap in report.gaps) or "none identified",
                evidence=format_evidence(state["evidence"], limit=16),
            ),
            InterviewQuestionList,
            system=prompts.INTERVIEW_SYSTEM,
        )
        return {"interview_questions": result.items}
