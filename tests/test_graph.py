"""End-to-end pipeline behaviour, including the grounding critic loop."""

from app.agents.graph import build_graph
from app.agents.nodes import CopilotNodes
from app.schemas.profile import EvidenceChunk
from app.schemas.tailor import ResumeBullet, TailorRequest
from app.services.copilot import CopilotService
from app.services.llm import get_llm
from app.services.retrieval import RetrievalService

JD = """We are hiring an AI/ML Engineer to build retrieval-augmented generation
systems in Python. You will design agentic pipelines, own evaluation, and ship
LLM features to production. Required: Python, RAG, FastAPI. Preferred: PyTorch."""


def _nodes(indexed_store, embedder, settings):
    retrieval = RetrievalService(indexed_store, embedder, settings)
    return CopilotNodes(get_llm(settings), retrieval, settings)


def test_full_pipeline_produces_grounded_output(indexed_store, embedder, settings):
    retrieval = RetrievalService(indexed_store, embedder, settings)
    graph = build_graph(get_llm(settings), retrieval, settings)
    result = graph.invoke(
        {"jd_text": JD, "tone": "professional", "grounding_retries": 0, "grounding_violations": []}
    )
    assert result["job"].title
    assert result["evidence"], "pipeline must retrieve evidence"
    assert result["match_report"].ats_score >= 0
    valid_ids = {chunk.id for chunk in result["evidence"]}
    for bullet in result["resume_bullets"]:
        assert bullet.evidence_ids
        assert set(bullet.evidence_ids) <= valid_ids


def test_critic_drops_bullets_with_invalid_citations(indexed_store, embedder, settings):
    nodes = _nodes(indexed_store, embedder, settings)
    evidence = [
        EvidenceChunk(
            id="ev-real-0",
            document_id="doc-1",
            document_title="Project",
            kind="project",
            text="Built a RAG pipeline.",
            position=0,
            score=0.9,
        )
    ]
    state = {
        "evidence": evidence,
        "resume_bullets": [
            ResumeBullet(text="Grounded bullet.", target_requirement="RAG",
                         evidence_ids=["ev-real-0"]),
            ResumeBullet(text="Hallucinated bullet.", target_requirement="Kubernetes",
                         evidence_ids=["ev-does-not-exist"]),
            ResumeBullet(text="Uncited bullet.", target_requirement="Go", evidence_ids=[]),
        ],
        "grounding_retries": 0,
    }
    result = nodes.verify_grounding(state)
    assert len(result["resume_bullets"]) == 1
    assert result["resume_bullets"][0].text == "Grounded bullet."
    assert len(result["grounding_violations"]) == 2


def test_retry_routing_stops_after_max_retries(indexed_store, embedder, settings):
    nodes = _nodes(indexed_store, embedder, settings)
    exhausted = {
        "grounding_violations": [],
        "resume_bullets": [],
        "grounding_retries": settings.max_grounding_retries + 5,
    }
    assert nodes.should_retry(exhausted) == "continue"


def test_service_run_persists_and_returns_response(indexed_store, settings):
    from app.db.session import init_db

    init_db()
    service = CopilotService(settings, indexed_store)
    response = service.run(TailorRequest(job_description=JD))
    assert response.run_id.startswith("run-")
    assert response.latency_ms >= 0
    assert response.job.title
