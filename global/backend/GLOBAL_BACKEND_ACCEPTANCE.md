# MINE-TRACE GLOBAL Backend Acceptance — Prompts 0–10

Date: 2026-10-03

## Overall state

**PASS for the backend code/test environment available in this run, with external-service validation blockers explicitly noted below.**

The frozen OpenAPI schema is `openapi/global-backend.openapi.json` with SHA-256:

`a8890a153a6d1fe6c487f0ae0f1fb5d14b4cd37eaf0186df6f1e9777555116ef`

## Acceptance matrix

| Requirement | State | Evidence from this audit |
|---|---|---|
| PostgreSQL is canonical | PASS | Runtime settings remain PostgreSQL-only; canonical health reports `canonical_postgresql`; Alembic offline PostgreSQL upgrade reaches `0002_semantic_index_outbox`. |
| Sync schema version/checksum/revisions/idempotency/conflicts | PASS | Prompt 3–4 contract and ingestion tests remain in the complete green suite. Exact replay/logical replay/conflict/newer/stale revision behavior is retained. |
| No local-authority workflows | PASS | Frozen OpenAPI has no evidence move, incident split, start/evaluate verification, raw evidence ingestion, or handover mutation route. Verification remains GET/read-only. |
| Semantic indexing is post-commit | PASS | Durable PostgreSQL semantic-index outbox remains canonical; indexing consumer executes separately after commit. Rollback/failure tests remain green. |
| Qdrant is derived retrieval data | PASS | Qdrant payload contains canonical references/filter metadata; canonical evidence remains PostgreSQL truth; rebuild originates from PostgreSQL. |
| Fleet semantic search hydrates via PostgreSQL | PASS | `POST /api/v1/search/semantic` embeds locally, retrieves candidate IDs through Qdrant, discards stale IDs, hydrates canonical evidence/timestamps/session/incident/provenance from PostgreSQL, and labels score as semantic similarity. |
| Semantic filters | PASS | Machine, component, model, site, time range and `top_k` are supported. Filters are sent to Qdrant when supported and rechecked against PostgreSQL hydration. |
| Semantic degraded behavior | PASS | Embedding/Qdrant failure returns typed `DEGRADED`; canonical APIs and sync remain independent. |
| Groq explicit fleet AI | PASS | `POST /api/v1/ai/analyze` is explicit action only. Provider receives canonical PostgreSQL context plus optional hydrated semantic evidence. Unknown evidence citations are rejected. |
| Groq is read-only | PASS | Groq provider exposes no mutation tools; AI service performs reads only and tests verify incident state is unchanged on malformed/provider failure. |
| Optional capability failure isolation | PASS | Qdrant, embedding, and Groq failure tests return degraded states without rolling back or disabling canonical relational behavior. |
| Complete backend test suite | PASS | `297 passed, 23 skipped` in 5.82s. The 23 skips are explicit real-service tests requiring opt-in PostgreSQL/Qdrant services. |
| Frozen OpenAPI | PASS | Export completed after Prompt 8–9 implementation and the complete backend regression run. |

## Backend commands run

```text
pytest -o addopts='' -q --tb=short
# 297 passed, 23 skipped in 5.82s

pytest -o addopts='' -q tests/global/test_fleet_semantic_search.py tests/global/test_groq_fleet_ai.py tests/unit/test_qdrant_service.py
# 24 passed

pytest -o addopts='' -q -rs tests/real_integration
# 23 skipped; opt-in external services not configured

MINE_TRACE_DATABASE_URL=postgresql+psycopg://... alembic upgrade head --sql
# PASS; PostgreSQL DDL reaches 0002_semantic_index_outbox

python scripts/export_openapi.py
# PASS
```

## Remaining blockers / limitations

1. **Live PostgreSQL was not available in this execution environment.** The real PostgreSQL migration and sync tests remain opt-in and were skipped rather than falsely reported as passing.
2. **Live Qdrant was not available.** Real Qdrant pipeline tests remain opt-in and were skipped. The Qdrant adapter/unit/global tests pass using deterministic doubles.
3. **Runtime provider packages are declared but not installed in this sandbox:** `psycopg`, `qdrant-client`, `fastembed`, and `groq` could not be imported here. Provider/model/service behavior is therefore validated through the repository abstractions and injected test clients, not a live Groq request or a downloaded FastEmbed model in this run.
4. No real API key or `.env` is committed or packaged. A deployment must install declared dependencies and inject PostgreSQL/Qdrant/Groq configuration separately.

These blockers do not change canonical failure semantics: lack of Qdrant/FastEmbed/Groq leaves PostgreSQL APIs and synchronization available, while lack of PostgreSQL itself correctly means the canonical global service cannot operate.
