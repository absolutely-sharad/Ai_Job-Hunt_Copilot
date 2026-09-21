"""Orchestration service: runs the graph and persists the result."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime

from app.agents.graph import build_graph
from app.core.config import Settings, get_settings
from app.core.logging import get_logger, log_event
from app.db.models import RunRecord
from app.db.session import session_scope
from app.schemas.tailor import TailorRequest, TailorResponse
from app.services.embeddings import get_embedder
from app.services.llm import get_llm
from app.services.retrieval import RetrievalService
from app.services.vectorstore import VectorStore

logger = get_logger(__name__)


class CopilotService:
    def __init__(self, settings: Settings | None = None, store: VectorStore | None = None):
        self.settings = settings or get_settings()
        self.store = store or VectorStore(self.settings)
        self.llm = get_llm(self.settings)
        self.embedder = get_embedder(self.settings)
        self.retrieval = RetrievalService(self.store, self.embedder, self.settings)
        self.graph = build_graph(self.llm, self.retrieval, self.settings)

    def run(self, request: TailorRequest, *, persist: bool = True) -> TailorResponse:
        started = time.perf_counter()
        run_id = f"run-{uuid.uuid4().hex[:10]}"

        final_state = self.graph.invoke(
            {
                "jd_text": request.job_description,
                "tone": request.tone,
                "include_cover_letter": request.include_cover_letter,
                "include_interview_prep": request.include_interview_prep,
                "grounding_retries": 0,
                "grounding_violations": [],
            }
        )

        latency_ms = int((time.perf_counter() - started) * 1000)
        response = TailorResponse(
            run_id=run_id,
            created_at=datetime.now(UTC),
            job=final_state["job"],
            match_report=final_state["match_report"],
            resume_bullets=final_state.get("resume_bullets", []),
            cover_letter=final_state.get("cover_letter", ""),
            interview_questions=final_state.get("interview_questions", []),
            evidence=final_state.get("evidence", []),
            grounding_violations=final_state.get("grounding_violations", []),
            latency_ms=latency_ms,
        )
        log_event(
            logger,
            logging.INFO,
            "tailor_run_complete",
            run_id=run_id,
            latency_ms=latency_ms,
            ats_score=response.match_report.ats_score,
            bullets=len(response.resume_bullets),
        )
        if persist:
            self._persist(response, request.job_description)
        return response

    @staticmethod
    def _persist(response: TailorResponse, jd_text: str) -> None:
        with session_scope() as session:
            session.add(
                RunRecord(
                    id=response.run_id,
                    job_title=response.job.title,
                    company=response.job.company,
                    ats_score=response.match_report.ats_score,
                    latency_ms=response.latency_ms,
                    jd_text=jd_text[:10000],
                    payload=response.model_dump(mode="json"),
                )
            )
