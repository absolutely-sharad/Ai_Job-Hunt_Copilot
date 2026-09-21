"""Requirement-aware retrieval: query expansion, MMR re-ranking, deduplication."""

from __future__ import annotations

import logging

from app.core.config import Settings, get_settings
from app.core.logging import get_logger, log_event
from app.schemas.job import JobDescription
from app.schemas.profile import EvidenceChunk
from app.services.embeddings import BaseEmbedder
from app.services.vectorstore import VectorStore

logger = get_logger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (na * nb)


def mmr_rerank(
    query_embedding: list[float],
    candidates: list[dict],
    top_k: int,
    lambda_mult: float,
) -> list[dict]:
    """Maximal Marginal Relevance: trade relevance against redundancy.

    Resume corpora repeat the same technologies across projects, so pure
    top-k similarity returns near-duplicates. MMR keeps the evidence diverse.
    """
    if not candidates:
        return []
    selected: list[dict] = []
    pool = candidates.copy()
    while pool and len(selected) < top_k:
        best, best_score = None, float("-inf")
        for candidate in pool:
            relevance = _cosine(query_embedding, candidate["embedding"])
            redundancy = max(
                (_cosine(candidate["embedding"], chosen["embedding"]) for chosen in selected),
                default=0.0,
            )
            score = lambda_mult * relevance - (1 - lambda_mult) * redundancy
            if score > best_score:
                best, best_score = candidate, score
        selected.append(best)
        pool.remove(best)
    return selected


class RetrievalService:
    """Retrieves grounded evidence for each requirement in a job description."""

    def __init__(
        self,
        store: VectorStore,
        embedder: BaseEmbedder,
        settings: Settings | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.settings = settings or get_settings()

    def search(self, query: str, top_k: int | None = None) -> list[EvidenceChunk]:
        top_k = top_k or self.settings.retrieval_top_k
        embedding = self.embedder.embed([query], is_query=True)[0]
        candidates = self.store.query(embedding, self.settings.retrieval_candidate_k)
        candidates = [c for c in candidates if c["score"] >= self.settings.min_similarity]
        reranked = mmr_rerank(embedding, candidates, top_k, self.settings.mmr_lambda)
        return [self._to_evidence(hit, query) for hit in reranked]

    def retrieve_for_job(self, job: JobDescription) -> list[EvidenceChunk]:
        """Expand the JD into per-requirement queries and merge the results.

        One query per requirement beats a single whole-JD query: it surfaces
        evidence for niche requirements that a averaged JD embedding buries.
        """
        queries = self._build_queries(job)
        merged: dict[str, EvidenceChunk] = {}
        for query in queries:
            for chunk in self.search(query, self.settings.retrieval_top_k):
                existing = merged.get(chunk.id)
                if existing is None or chunk.score > existing.score:
                    merged[chunk.id] = chunk
        evidence = sorted(merged.values(), key=lambda c: c.score, reverse=True)
        log_event(
            logger,
            logging.INFO,
            "retrieval_complete",
            queries=len(queries),
            evidence=len(evidence),
        )
        return evidence

    def _build_queries(self, job: JobDescription) -> list[str]:
        queries = [f"{job.title} {' '.join(job.ats_keywords[:8])}".strip()]
        queries += [
            f"{req.skill} {req.context}".strip()
            for req in job.requirements[: self.settings.retrieval_candidate_k]
        ]
        queries += job.responsibilities[:5]
        return [q for q in dict.fromkeys(q.strip() for q in queries) if len(q) > 2]

    @staticmethod
    def _to_evidence(hit: dict, query: str) -> EvidenceChunk:
        meta = hit["metadata"]
        return EvidenceChunk(
            id=hit["id"],
            document_id=str(meta.get("document_id", "")),
            document_title=str(meta.get("document_title", "")),
            kind=str(meta.get("kind", "note")),  # type: ignore[arg-type]
            text=hit["text"],
            position=int(meta.get("position", 0)),
            score=round(float(hit["score"]), 4),
            matched_requirement=query,
        )
