# MINE-TRACE Real Qdrant Integration Test Suite

This suite adds **21 opt-in integration tests** covering the complete canonical-evidence -> embedding -> real Qdrant -> semantic-search -> canonical-hydration path.

## Safety boundary

The suite never uses the application collection name. Each test process generates a random resource name with the prefix:

```text
mine_trace_it_<random>
```

Only Qdrant collections with that prefix can be deleted by the suite. PostgreSQL data is isolated in a random schema with the same prefix and only that schema is dropped during teardown. No production collection/database cleanup path exists in the tests.

## Required services

Use dedicated non-production services. A convenience Compose file is included:

```bash
docker compose -f docker-compose.real-integration.yml up -d
```

Install development dependencies:

```bash
python -m pip install -e '.[dev]'
```

Set test-only configuration:

```bash
export MINE_TRACE_RUN_REAL_QDRANT_INTEGRATION=1
export MINE_TRACE_TEST_QDRANT_URL=http://127.0.0.1:6333
export MINE_TRACE_TEST_POSTGRES_URL=postgresql+psycopg://mine_trace:mine_trace@127.0.0.1:55432/mine_trace_test
```

If the isolated Qdrant uses authentication, additionally set:

```bash
export MINE_TRACE_TEST_QDRANT_API_KEY=...
```

Run only the real pipeline suite:

```bash
pytest -q tests/real_integration/test_qdrant_pipeline_real.py
```

Expected collected count: **21 tests**.

Run the ordinary regression suite without the external integration tests:

```bash
pytest -q --ignore=tests/real_integration
```

## Embedding boundary

The tests use a deterministic test-only `EmbeddingProvider` so vector ranking is repeatable. The vector database is still a real Qdrant instance, and canonical hydration uses real PostgreSQL through SQLAlchemy/`SQLAlchemyUnitOfWork`. The suite intentionally does not make a third-party embedding API another availability dependency of the Qdrant integration boundary.

## Coverage

The 21 tests map one-to-one to the requested checks:

1. Qdrant connectivity
2. collection creation
3. collection compatibility
4. vector insertion
5. canonical `evidence_id` payload
6. deterministic/idempotent upsert
7. batch indexing
8. re-indexing after canonical text update
9. machine filtering
10. component filtering
11. top-K search
12. PostgreSQL canonical hydration
13. stale Qdrant ID rejection
14. deleted canonical evidence rejection while stale vector remains
15. vector deletion preserves canonical evidence
16. empty Qdrant collection leaves canonical backend intact
17. complete Qdrant rebuild
18. Qdrant outage -> degraded semantic state
19. canonical FastAPI reads continue during Qdrant outage
20. semantic result labelled `SEMANTIC`
21. similarity ranking score is not exposed as factual confidence/probability
