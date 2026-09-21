"""Offline evaluation harness for retrieval quality and generation grounding.

Metrics
-------
Retrieval (per query, against labelled relevant documents):
  precision@k  share of retrieved chunks that come from a relevant document
  recall@k     share of relevant documents represented in the retrieved set
  MRR          reciprocal rank of the first relevant chunk

Generation (per job description, over the full pipeline):
  grounding_rate     bullets citing at least one real evidence id
  violation_count    bullets the critic rejected as unverifiable
  keyword_coverage   share of JD ATS keywords appearing in the generated bullets
  latency_ms         wall-clock pipeline time

Run offline (no API key):   LLM_PROVIDER=fake python eval/run_eval.py
Run against Gemini:         LLM_PROVIDER=gemini python eval/run_eval.py
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATASET_PATH = Path(__file__).parent / "dataset.json"
RESULTS_PATH = Path(__file__).parent / "results.json"


def build_index(dataset: dict, settings):
    from app.schemas.profile import DocumentIn
    from app.services.embeddings import get_embedder
    from app.services.ingestion import IngestionService
    from app.services.vectorstore import VectorStore

    store = VectorStore(settings)
    store.reset()
    service = IngestionService(store, get_embedder(settings), settings)
    for document in dataset["corpus"]:
        service.ingest(
            DocumentIn(
                title=document["title"], kind=document["kind"], content=document["content"]
            )
        )
    return store


def evaluate_retrieval(store, settings, dataset: dict, top_k: int) -> dict:
    from app.services.embeddings import get_embedder
    from app.services.retrieval import RetrievalService

    service = RetrievalService(store, get_embedder(settings), settings)
    rows = []
    for case in dataset["queries"]:
        retrieved = service.search(case["query"], top_k=top_k)
        relevant = set(case["relevant_document_titles"])
        titles = [chunk.document_title for chunk in retrieved]

        hits = [title in relevant for title in titles]
        precision = sum(hits) / len(hits) if hits else 0.0
        recall = len(relevant & set(titles)) / len(relevant) if relevant else 0.0
        mrr = next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0.0)

        rows.append(
            {
                "query": case["query"],
                "precision_at_k": round(precision, 3),
                "recall_at_k": round(recall, 3),
                "mrr": round(mrr, 3),
                "top_title": titles[0] if titles else None,
            }
        )
    return {
        "top_k": top_k,
        "per_query": rows,
        "mean_precision_at_k": round(statistics.fmean(r["precision_at_k"] for r in rows), 3),
        "mean_recall_at_k": round(statistics.fmean(r["recall_at_k"] for r in rows), 3),
        "mean_mrr": round(statistics.fmean(r["mrr"] for r in rows), 3),
    }


def evaluate_generation(store, settings, dataset: dict) -> dict:
    from app.schemas.tailor import TailorRequest
    from app.services.copilot import CopilotService

    service = CopilotService(settings, store)
    rows = []
    for case in dataset["job_descriptions"]:
        response = service.run(
            TailorRequest(job_description=case["text"], include_interview_prep=False),
            persist=False,
        )
        valid_ids = {chunk.id for chunk in response.evidence}
        bullets = response.resume_bullets
        grounded = [b for b in bullets if set(b.evidence_ids) & valid_ids]
        bullet_text = " ".join(b.text.lower() for b in bullets)
        keywords = [k.lower() for k in response.job.ats_keywords]
        covered = [k for k in keywords if k in bullet_text]

        rows.append(
            {
                "job": case["name"],
                "parsed_title": response.job.title,
                "ats_score": response.match_report.ats_score,
                "bullets": len(bullets),
                "grounding_rate": round(len(grounded) / len(bullets), 3) if bullets else 0.0,
                "violation_count": len(response.grounding_violations),
                "keyword_coverage": round(len(covered) / len(keywords), 3) if keywords else 0.0,
                "latency_ms": response.latency_ms,
            }
        )
    return {
        "per_job": rows,
        "mean_grounding_rate": round(statistics.fmean(r["grounding_rate"] for r in rows), 3),
        "mean_keyword_coverage": round(statistics.fmean(r["keyword_coverage"] for r in rows), 3),
        "total_violations": sum(r["violation_count"] for r in rows),
        "mean_latency_ms": int(statistics.fmean(r["latency_ms"] for r in rows)),
    }


def print_report(results: dict) -> None:
    retrieval, generation = results["retrieval"], results["generation"]
    width = 74
    print("=" * width)
    print(f"  EVAL REPORT — provider={results['provider']}  top_k={retrieval['top_k']}")
    print("=" * width)
    print("\nRETRIEVAL")
    print(f"  {'query':<44}{'P@k':>8}{'R@k':>8}{'MRR':>8}")
    for row in retrieval["per_query"]:
        print(
            f"  {row['query'][:42]:<44}{row['precision_at_k']:>8.2f}"
            f"{row['recall_at_k']:>8.2f}{row['mrr']:>8.2f}"
        )
    print(
        f"  {'MEAN':<44}{retrieval['mean_precision_at_k']:>8.2f}"
        f"{retrieval['mean_recall_at_k']:>8.2f}{retrieval['mean_mrr']:>8.2f}"
    )
    print("\nGENERATION")
    print(f"  {'job':<24}{'ATS':>6}{'bullets':>9}{'grounded':>10}{'keywords':>10}{'ms':>8}")
    for row in generation["per_job"]:
        print(
            f"  {row['job'][:22]:<24}{row['ats_score']:>6}{row['bullets']:>9}"
            f"{row['grounding_rate']:>10.2f}{row['keyword_coverage']:>10.2f}{row['latency_ms']:>8}"
        )
    print(
        f"\n  mean grounding rate : {generation['mean_grounding_rate']:.2f}"
        f"\n  mean keyword cover  : {generation['mean_keyword_coverage']:.2f}"
        f"\n  critic violations   : {generation['total_violations']}"
    )
    print("=" * width)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval and generation quality.")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--skip-generation", action="store_true")
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="copilot-eval-")
    os.environ.setdefault("LLM_PROVIDER", "fake")
    os.environ["CHROMA_PATH"] = f"{tmp}/chroma"
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/eval.db"

    from app.core.config import get_settings

    settings = get_settings()
    dataset = json.loads(DATASET_PATH.read_text())

    store = build_index(dataset, settings)
    results = {
        "provider": settings.llm_provider,
        "embedding_model": settings.embedding_model,
        "retrieval": evaluate_retrieval(store, settings, dataset, args.top_k),
        "generation": {}
        if args.skip_generation
        else evaluate_generation(store, settings, dataset),
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print_report(results)
    print(f"\nWrote {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
