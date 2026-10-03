# MINE-TRACE Semantic Benchmark Execution Status

## Current container result

**Status: NOT RUN against external services**

The benchmark dataset and runner were validated locally, but this execution container does not contain the deployment's Qdrant connection configuration or an isolated benchmark PostgreSQL target. The runner was intentionally stopped with:

```text
RuntimeError: MINE_TRACE_QDRANT_URL is required for actual Qdrant benchmark execution
```

No local cosine-similarity substitute, FAISS, Chroma, in-memory Qdrant mode, or fabricated metric values were used.

## Static/local validation completed

- Dataset: 36 evidence records, 20 labelled queries — **PASS**
- Required linguistic/distractor coverage — **PASS**
- Metric calculation tests — **8/8 PASS**
- Runner source compiles — **PASS**
- Production-shaped dependencies used by runner: `EmbeddingProvider`, `CanonicalEvidenceIndexingService`, `QdrantService`, `SemanticHistoryService` — **PASS**
- Isolated resource prefix guard: `mine_trace_bench_` — **PASS**
- Production collection deletion path in benchmark: **none**

## What remains to produce numeric benchmark results

Run the documented command in an environment containing:

- `MINE_TRACE_QDRANT_URL`
- `MINE_TRACE_QDRANT_API_KEY` where required
- `MINE_TRACE_BENCHMARK_POSTGRES_URL`
- selected configured embedding provider/model

The runner will then overwrite the `results/` files with actual measured metrics, failed queries, score distributions, candidate-threshold tradeoffs, and latency measurements.
