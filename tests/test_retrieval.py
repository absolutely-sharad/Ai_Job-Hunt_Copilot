"""Retrieval behaviour: ranking, MMR diversity, and requirement expansion."""

from app.schemas.job import JobDescription, SkillRequirement
from app.services.retrieval import RetrievalService, mmr_rerank


def test_search_ranks_relevant_chunk_first(indexed_store, embedder, settings):
    service = RetrievalService(indexed_store, embedder, settings)
    results = service.search("ChromaDB RAG pipeline grounding critic")
    assert results
    assert "RAG" in results[0].text or "ChromaDB" in results[0].text


def test_search_returns_evidence_ids(indexed_store, embedder, settings):
    service = RetrievalService(indexed_store, embedder, settings)
    results = service.search("React Node.js clients")
    assert all(chunk.id.startswith("ev-") for chunk in results)
    assert all(0.0 <= chunk.score <= 1.0 for chunk in results)


def test_retrieve_for_job_merges_and_dedupes(indexed_store, embedder, settings):
    service = RetrievalService(indexed_store, embedder, settings)
    job = JobDescription(
        title="AI/ML Engineer",
        requirements=[
            SkillRequirement(skill="RAG", context="retrieval pipelines"),
            SkillRequirement(skill="React", context="frontend"),
        ],
        ats_keywords=["Python", "RAG"],
    )
    evidence = service.retrieve_for_job(job)
    ids = [chunk.id for chunk in evidence]
    assert len(ids) == len(set(ids)), "evidence must be deduplicated"
    assert evidence == sorted(evidence, key=lambda c: c.score, reverse=True)


def _mmr_candidates() -> list[dict]:
    return [
        {"id": "a", "embedding": [1.0, 0.0], "score": 1.0},
        {"id": "b", "embedding": [0.99, 0.01], "score": 0.99},  # near-duplicate of "a"
        {"id": "c", "embedding": [0.0, 1.0], "score": 0.2},  # diverse but less relevant
    ]


def test_mmr_always_picks_the_most_relevant_first():
    assert mmr_rerank([1.0, 0.0], _mmr_candidates(), top_k=2, lambda_mult=0.65)[0]["id"] == "a"


def test_low_lambda_prefers_diversity_over_the_duplicate():
    """lambda < 0.5 weights redundancy penalty above relevance."""
    selected = mmr_rerank([1.0, 0.0], _mmr_candidates(), top_k=2, lambda_mult=0.4)
    assert selected[1]["id"] == "c"


def test_high_lambda_prefers_relevance_and_keeps_the_duplicate():
    """lambda > 0.5 behaves closer to plain top-k similarity."""
    selected = mmr_rerank([1.0, 0.0], _mmr_candidates(), top_k=2, lambda_mult=0.9)
    assert selected[1]["id"] == "b"


def test_mmr_respects_top_k_and_empty_input():
    assert len(mmr_rerank([1.0, 0.0], _mmr_candidates(), top_k=2, lambda_mult=0.65)) == 2
    assert mmr_rerank([1.0, 0.0], [], top_k=3, lambda_mult=0.65) == []


def test_empty_store_returns_no_results(store, embedder, settings):
    service = RetrievalService(store, embedder, settings)
    assert service.search("anything at all") == []
