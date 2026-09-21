# Evaluation harness

```bash
make eval        # offline, deterministic (LLM_PROVIDER=fake)
make eval-live   # against Gemini (needs GOOGLE_API_KEY)
python eval/run_eval.py --top-k 8 --skip-generation
```

## Metrics

**Retrieval** (per query in `dataset.json`, against labelled relevant documents)

| Metric | Meaning |
|---|---|
| `precision@k` | Share of retrieved chunks from a relevant document — measures noise |
| `recall@k` | Share of relevant documents represented — measures coverage |
| `MRR` | Reciprocal rank of the first relevant chunk — measures ordering |

**Generation** (per job description, full pipeline)

| Metric | Meaning |
|---|---|
| `grounding_rate` | Bullets citing at least one real evidence ID. Target: 1.00 |
| `violation_count` | Bullets the critic rejected as unverifiable |
| `keyword_coverage` | Share of JD ATS keywords appearing in the bullets |
| `latency_ms` | Wall-clock pipeline time |

## Interpreting offline runs

The fake embedder is hash-based and lexical, so semantic queries like "React frontend
development" score near zero. That is expected: offline numbers verify the harness and pipeline
wiring, not retrieval quality. Use `make eval-live` for real numbers.

## Using it to tune

Change one variable at a time in `.env`, re-run, and compare `eval/results.json`:

- `CHUNK_SIZE` / `CHUNK_OVERLAP` — larger chunks raise recall, lower precision
- `RETRIEVAL_TOP_K` — more evidence, more noise in the prompt
- `MMR_LAMBDA` — → 1.0 is pure relevance; → 0.0 is pure diversity

Extend `dataset.json` with your own documents and labelled queries; the harness picks them up
with no code change.
