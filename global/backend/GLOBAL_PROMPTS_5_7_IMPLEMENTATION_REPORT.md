# MINE-TRACE Global — Prompts 5–7 Implementation Report

## Scope

Implemented sequentially on the accepted `g_back_prompt0_4` backend:

1. Prompt 5 — remove remaining global local-authority behavior.
2. Prompt 6 — implement exact relational fleet read/query APIs.
3. Prompt 7 — implement durable post-commit semantic indexing.

No frontend work was performed.

---

## Prompt 5 — Global backend is synchronization/read oriented

### Authority removed

The global HTTP surface no longer exposes central mutation endpoints for:

- raw machine-event, maintenance-record, or human-observation ingestion;
- incident evidence move/reassignment;
- incident splitting;
- verification start;
- due-verification evaluation;
- recurrence/lifecycle execution;
- handover mutation;
- return-to-service decisions.

The only POST routes remaining in the global versioned router are:

- `POST /api/v1/sync/packages` — authenticated synchronization ingestion;
- `POST /api/v1/incidents/{incident_id}/ai-analysis` — explicit advisory/read-only AI analysis.

### Verification boundary

`app/services/verification.py` is now a pure `VerificationQueryService`.
It can only read synchronized verification outcomes and evidence references.
It contains no lifecycle transition, timer, recurrence, start, or evaluation logic.

The verification API now contains only:

- `GET /api/v1/incidents/{incident_id}/verifications`
- `GET /api/v1/verifications/{run_id}`

### Repository boundary

Removed repository primitives whose only global purpose was local authority:

- incident-evidence link deactivation;
- pending verification-run selection;
- due verification-run selection.

`app/domain/lifecycle.py` is retained only as legacy edge vocabulary for compatibility with existing source/tests. No global API or service imports it to make a lifecycle, verification, recurrence, or return-to-service decision.

### Negative contract validation

`tests/global/test_global_read_only_authority.py` proves the absent mutation paths and confirms synchronized verification remains readable.

---

## Prompt 6 — Exact canonical fleet reads

### Required routes

Implemented/retained:

- `GET /health`
- `GET /api/v1/fleet/overview`
- `GET /api/v1/machines`
- `GET /api/v1/machines/{machine_id}`
- `GET /api/v1/machines/{machine_id}/sessions`
- `GET /api/v1/machines/{machine_id}/incidents`
- `GET /api/v1/incidents`
- `GET /api/v1/incidents/{incident_id}`
- `GET /api/v1/maintenance-queue`
- `GET /api/v1/analytics/summary`
- `GET /api/v1/analytics/incidents/by-status`
- `GET /api/v1/analytics/incidents/by-site`
- `GET /api/v1/analytics/incidents/trend`
- `GET /api/v1/sync/health`
- `GET /api/v1/sync/conflicts`

Existing read-only component, evidence/audit, evidence-bundle and capability endpoints remain available.

### Incident filters

`GET /api/v1/incidents` filters relationally by:

- machine;
- component;
- start/end activity time;
- `status` or `state`;
- machine model;
- site.

When both `status` and `state` are supplied, they must match.

### Machine reads

`GET /api/v1/machines` supports:

- pagination;
- search;
- site;
- machine type;
- model;
- latest sync receipt/acknowledgement metadata.

### Fleet overview

Returns only canonical facts:

- machine count;
- recent synchronized sessions;
- unresolved incident count;
- synchronized verification-result counts;
- latest receipt/acknowledgement time;
- acknowledgement-status counts;
- unresolved sync-conflict count.

No health, uptime, productivity, risk, availability, or predictive-maintenance score is generated.

### Maintenance queue

The queue contains unresolved canonical incidents and their latest synchronized maintenance/verification facts.

Ordering is deterministic and documented in the response:

`due_time_nulls_last,due_time_asc,updated_at_asc,incident_id_asc`

No predictive priority/risk score is created.

### Sync health

Canonical database/ingestion information is separate from optional:

- semantic/Qdrant capability;
- embedding capability;
- AI capability.

The backend does not invent a staleness threshold. `stale` is only calculated when the caller explicitly supplies `stale_after_hours`; otherwise it remains unset while exact receipt times remain available.

### Analytics

All analytics use SQLAlchemy relational queries over canonical tables. Qdrant is not accessed.

Provided:

- exact aggregate summary;
- incident counts by status;
- incident counts by site;
- incident daily trend;
- verification completion rate derived from canonical verification rows.

### Prompt 6 tests

`tests/global/test_fleet_read_apis.py` covers:

- empty fleet;
- `/health`;
- pagination;
- multiple sites/models;
- session ordering;
- all required incident filters;
- maintenance queue ordering/content;
- sync recency;
- sync conflict metadata;
- relational analytics with no Qdrant capability configured.

---

## Prompt 7 — Durable post-commit semantic indexing

### Durable PostgreSQL outbox

Added canonical-derived-work table:

`semantic_index_outbox`

with status values:

- `PENDING`
- `INDEXED`
- `FAILED_RETRYABLE`
- `SKIPPED_INELIGIBLE`

It also records:

- canonical `evidence_id`;
- source report revision;
- attempt count;
- last attempt time;
- indexed time;
- last error;
- created/updated timestamps.

Migration:

`migrations/versions/0002_semantic_index_outbox.py`

The original Prompt-2 initial migration remains unchanged. The new revision cleanly follows `0001_global_initial`.

### Exact transaction boundary

On an accepted synchronization package:

1. canonical machine/session/incident/evidence/maintenance/verification/report/receipt data is written in the canonical transaction;
2. selected `important_text_evidence` receives an outbox row in that same transaction;
3. an uncommitted outbox row is not visible to the separate indexing consumer;
4. `GlobalSyncIngestionService.ingest()` returns only after the canonical transaction commits;
5. the API schedules derived indexing only after that return/commit;
6. the durable coordinator re-reads the outbox and canonical evidence from a separate database session;
7. embedding/Qdrant work occurs outside the canonical transaction.

A rollback therefore produces neither canonical evidence nor a durable indexing item and no vector is written.

### Eligibility

`SemanticDocumentExtractor` embeds only non-empty canonical string content.
Numeric/boolean-only telemetry is not converted into invented prose and becomes `SKIPPED_INELIGIBLE`.

### Canonical hydration before indexing

Every indexing attempt re-reads the evidence row from PostgreSQL. It also obtains canonical relationship/filter metadata from PostgreSQL:

- evidence ID;
- machine ID;
- component ID where available;
- incident ID where available;
- session ID where available;
- machine type;
- model;
- site.

### Qdrant payload

The enriched Qdrant path stores only derived retrieval references/filter metadata. It does **not** duplicate canonical payload, provenance, semantic text, audit history, or incident truth into Qdrant.

### Failure semantics

Embedding or Qdrant failure:

- leaves the accepted synchronization transaction committed;
- leaves canonical evidence intact;
- updates durable status to `FAILED_RETRYABLE`;
- records the last error;
- permits later `retry_pending()` or full rebuild.

### Rebuild

`DurableSemanticIndexingCoordinator.rebuild_from_postgresql()`:

1. deletes only the disposable Qdrant collection;
2. resets PostgreSQL outbox work;
3. re-reads selected canonical evidence;
4. deterministically skips ineligible rows again;
5. recreates vectors from canonical PostgreSQL truth.

Deleting Qdrant therefore cannot delete fleet truth.

### Prompt 7 tests

`tests/global/test_durable_semantic_indexing.py` proves:

- indexing is not performed before canonical commit;
- rollback creates no vector/outbox row;
- Qdrant failure does not roll back PostgreSQL;
- embedding failure does not roll back PostgreSQL;
- failures become retryable durable status;
- canonical IDs and machine filter metadata reach the semantic vector path;
- full rebuild restores deleted vectors;
- numeric-only canonical evidence is skipped deterministically.

`tests/unit/test_qdrant_service.py` additionally verifies the actual Qdrant adapter payload contains canonical filter references and excludes canonical body/provenance/text.

---

## Files changed relative to accepted Prompt 0–4 backend

### Added

- `app/api/analytics.py`
- `app/api/fleet.py`
- `app/api/maintenance.py`
- `app/models/semantic_index.py`
- `app/schemas/analytics.py`
- `app/schemas/fleet.py`
- `app/schemas/maintenance.py`
- `app/schemas/sync_reads.py`
- `app/services/fleet_queries.py`
- `migrations/versions/0002_semantic_index_outbox.py`
- `tests/global/test_durable_semantic_indexing.py`
- `tests/global/test_fleet_read_apis.py`
- `tests/global/test_global_read_only_authority.py`
- `GLOBAL_PROMPTS_5_7_IMPLEMENTATION_REPORT.md`

### Modified

- `app/api/incidents.py`
- `app/api/machines.py`
- `app/api/router.py`
- `app/api/sync.py`
- `app/api/verification.py`
- `app/core/capabilities.py`
- `app/domain/enums.py`
- `app/domain/lifecycle.py`
- `app/integrations/qdrant/client.py`
- `app/main.py`
- `app/models/__init__.py`
- `app/repositories/interfaces.py`
- `app/repositories/sqlalchemy.py`
- `app/schemas/incidents.py`
- `app/schemas/semantic_document.py`
- `app/schemas/verification.py`
- `app/services/evidence_bundle.py`
- `app/services/overview.py`
- `app/services/semantic_documents.py`
- `app/services/semantic_indexing.py`
- `app/services/sync_ingestion.py`
- `app/services/verification.py`
- `tests/global/test_global_schema_metadata.py`
- `tests/unit/test_qdrant_service.py`

---

## Validation performed

### Passed

- `python -m compileall -q app`
- `python -c "import app.main"`
- `python -m pytest -q tests/global tests/unit/test_qdrant_service.py`
  - all tests passed;
  - global suite contains 59 tests;
  - Qdrant unit suite contains 15 tests.
- `python -m pytest --collect-only -q`
  - 302 tests collected; no collection errors.
- `alembic upgrade head --sql`
  - PostgreSQL DDL generation passed through `0002_semantic_index_outbox`.

### Whole legacy repository suite

`python -m pytest --tb=no`

Result:

- 219 passed
- 23 skipped
- 10 failed
- 50 errors

All 10 failures and all 50 setup errors are the already-known legacy tests that construct a SQLite `Settings(database_url="sqlite://...")`. The PostgreSQL-only global settings validator rejects them before their test bodies execute. This is the same intentional Prompt-1 incompatibility class; PostgreSQL enforcement was not weakened to make local-era tests green.

No Prompt 5–7 global test is among those failures/errors.

### Live PostgreSQL limitation

A live PostgreSQL server is not available in this execution environment, so the new `0002` migration was validated via PostgreSQL Alembic offline DDL generation rather than a live database upgrade. Existing opt-in real PostgreSQL tests remain available for an integration environment.

---

## Packaging checks

The delivery ZIP excludes:

- `.pytest_cache`;
- `__pycache__` / bytecode;
- virtual environments;
- `node_modules`;
- real `.env` files;
- database files/dumps.

`.env.example` remains placeholder-only.
