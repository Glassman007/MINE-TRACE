#!/usr/bin/env bash
set -euo pipefail
python -m benchmarks.semantic_quality.runner \
  --results-dir benchmarks/semantic_quality/results \
  --analysis-k "${MINE_TRACE_BENCHMARK_ANALYSIS_K:-20}" \
  "${@}"
