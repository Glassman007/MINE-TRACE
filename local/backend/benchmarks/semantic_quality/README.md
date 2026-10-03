# MINE-TRACE semantic-quality benchmark

This benchmark does not modify canonical application architecture. It measures the actual production-shaped semantic retrieval path using isolated benchmark resources:

```text
synthetic labelled benchmark query
→ canonical PostgreSQL evaluation row
→ configured EmbeddingProvider / configured model
→ actual Qdrant vector search
→ Qdrant top-K evidence IDs
→ canonical PostgreSQL hydration through SemanticHistoryService
→ relevance evaluation
```

It intentionally does **not** benchmark a standalone NumPy/Python cosine-similarity function.

## Dataset

`dataset/evidence.jsonl` contains 36 synthetic canonical-style evidence records. `dataset/queries.jsonl` contains 20 labelled queries with relevant and explicit distractor evidence IDs, machine/component scope, a primary relevance category, and coverage labels.

The corpus covers paraphrases, abbreviations, technician terminology, operator terminology, differently worded symptoms, causally unrelated but semantically similar faults, different-machine distractors, same-machine history, different-component distractors, and same-component history.

## Isolation and safety

Every run creates:

- PostgreSQL schema `mine_trace_bench_<random>`
- Qdrant semantic collection `mine_trace_bench_<random>`
- Qdrant Cloud-Inference bridge collection `mine_trace_bench_<random>_inference`

Cleanup refuses names outside the `mine_trace_bench_` namespace. The production semantic collection is never deleted or rebuilt by this benchmark.

`MINE_TRACE_BENCHMARK_POSTGRES_URL` is mandatory; the runner does not silently use the production canonical database URL.

## Required configuration

The normal MINE-TRACE semantic settings must identify the selected production embedding model and Qdrant cluster:

```bash
export MINE_TRACE_SEMANTIC_SEARCH_ENABLED=true
export MINE_TRACE_QDRANT_URL='https://<cluster>.cloud.qdrant.io'
export MINE_TRACE_QDRANT_API_KEY='<secret>'
export MINE_TRACE_QDRANT_DISTANCE=cosine
export MINE_TRACE_EMBEDDING_PROVIDER=qdrant_cloud_inference
export MINE_TRACE_EMBEDDING_MODEL=sentence-transformers/all-minilm-l6-v2

# Mandatory isolated evaluation database target.
export MINE_TRACE_BENCHMARK_POSTGRES_URL='postgresql+psycopg://user:pass@host:5432/mine_trace_benchmark'
```

Secrets are read from environment only and are never written to benchmark reports.

## Reproducible commands

Validate the labelled dataset without contacting external services:

```bash
python -m benchmarks.semantic_quality.runner --validate-dataset-only
```

Run the production-shaped benchmark with the configured top-K (default `MINE_TRACE_SEMANTIC_TOP_K`, currently commonly 5) and no guessed threshold:

```bash
python -m benchmarks.semantic_quality.runner \
  --results-dir benchmarks/semantic_quality/results \
  --analysis-k 20
```

Explicitly benchmark another K:

```bash
python -m benchmarks.semantic_quality.runner --top-k 10 --analysis-k 30
```

Evaluate a candidate threshold without freezing it into production:

```bash
python -m benchmarks.semantic_quality.runner --top-k 5 --threshold 0.72 --analysis-k 20
```

## Metrics

The runner produces:

- Recall@K
- Precision@K
- MRR
- explicit distractor rejection
- same-machine scope accuracy
- same-component scope accuracy
- Qdrant search latency
- end-to-end retrieval latency
- relevant / irrelevant / explicit-distractor score distributions
- candidate similarity thresholds with measured precision/recall/F1 tradeoffs

No threshold is automatically selected. Threshold candidates are evidence for later production policy, not a confidence calibration.
