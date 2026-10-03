# MINE-TRACE Global — Prompts 3–4 Implementation Report

Date: 2026-10-03

## Scope completed

Implemented sequentially on the accepted `g_back_prompt0_2` baseline:

- Prompt 3 — shared/versioned synchronization contracts, checksum policy, revision policy, edge authentication boundary, generated JSON Schemas.
- Prompt 4 — authenticated transactional `POST /api/v1/sync/packages` ingestion with explicit-ID routing, durable receipts/conflicts, idempotency, and post-commit derived semantic dispatch.

The accepted Prompt 2 Alembic initial revision and canonical model definitions were left unchanged during the final audit.

## Prompt 3 — contract decisions

### Versioning

- Current sync version: `1.0.0`.
- Supported major: `1`.
- Top-level `schema_version` is prevalidated before business-field model parsing.
- Unsupported major versions are rejected; no renamed/missing-field guessing is performed.
- Nested report/manifest versions must equal the envelope version.

### Contract models

Runtime source: `app/contracts/sync.py`.

Defined:

- `MachineSessionReport`
- `EvidenceManifest`
- `IncidentUpdate`
- `SyncEnvelope`
- `SyncAcknowledgement`
- machine/component/session snapshots
- maintenance action snapshots
- synchronized verification snapshots
- important-text evidence references
- optional policy-selected raw evidence
- sync metadata

Generated language-neutral snapshots are under `shared/schema/` and are tested against the runtime Pydantic models to prevent drift.

### Checksum

- Algorithm: SHA-256.
- Wire form: `sha256:<64 lowercase hex>`.
- Hash input: complete validated envelope except `sync_metadata.checksum` itself.
- Canonical serialization: `MINE-TRACE Canonical JSON v1`, documented in `GLOBAL_SYNC_CONTRACT.md`.
- UUIDs, timestamps, decimals, map ordering, arrays and finite numeric formatting have deterministic rules.
- Cross-language reference test vector is locked in automated tests.

### Revision fingerprint

A second SHA-256 fingerprint is calculated from logical revision content, excluding only:

- `package_id`
- `sync_metadata`

This permits a new package ID carrying identical machine/session/report-revision content to be recognized as a logical duplicate without duplicating canonical data.

### Edge authentication

Replaceable interface: `EdgeAuthenticator`.

Current MVP mechanism:

- `X-Mine-Trace-Node-Id: <machine UUID>`
- `Authorization: Bearer <token>`
- deployment configuration stores only `sha256:<digest>` values in `MINE_TRACE_EDGE_NODE_TOKEN_HASHES`
- comparison uses `hmac.compare_digest`
- authenticated node identity must equal `SyncEnvelope.source_machine_id`

No raw token is committed. Limitations and replacement path to mTLS/signed requests are documented in `GLOBAL_SYNC_CONTRACT.md`.

## Locked revision/idempotency policy

1. Same machine + package ID + checksum: exact redelivery; return the previous acknowledgement; no writes.
2. Same package ID with different checksum: `PACKAGE_ID_REUSE` conflict; accepted canonical state is not overwritten.
3. Same machine/session/report revision + same logical fingerprint under a new package ID: `DUPLICATE` receipt; canonical report/evidence/link/action/verification records are not duplicated.
4. Same logical revision + different fingerprint: `SAME_REVISION_CONTENT_MISMATCH` conflict.
5. Newer revision: accepted; earlier `session_reports` revision remains unchanged/auditable.
6. Older unseen revision after a newer accepted revision: `OUT_OF_ORDER_REVISION` conflict; current state is not overwritten.
7. Previously accepted historical revision redelivery remains idempotent.
8. Stable edge evidence UUID/source identity is retained; the global backend does not mint replacement evidence IDs.

## Prompt 4 — transaction behavior

Endpoint: `POST /api/v1/sync/packages`.

The route performs:

1. edge authentication
2. major schema-version validation
3. full explicit identity/relationship validation
4. checksum validation
5. package/revision idempotency decision
6. machine/component/session validation/upsert
7. explicit incident persistence
8. evidence deduplication by stable identity
9. incident-session and incident-evidence relationship persistence
10. maintenance and synchronized verification persistence
11. report-revision persistence
12. explicit conflict handling
13. sync receipt persistence
14. one canonical SQLAlchemy transaction commit
15. post-commit semantic work dispatch using only `important_text_evidence` IDs
16. `SyncAcknowledgement` response

No AI classification, global incident linking, recurrence inference, verification execution, evidence reassignment or browser/server silent conflict merge is performed.

### Transaction failure semantics

All canonical mutations for an accepted package occur inside one `Session.begin()` transaction. An automated rollback test deliberately changes machine/session projections and then triggers an incompatible evidence-identity error; after rollback, the earlier machine projection, session revision, report count and receipt count remain unchanged.

### Derived capability boundary

The sync transaction does not import or invoke Qdrant, embeddings or AI.

After canonical commit, the API schedules selected evidence IDs to the already-existing semantic indexing service. The wrapper catches optional derived-service failure and logs it. Tests simulate both `qdrant unavailable` and `embedding unavailable`; canonical PostgreSQL-equivalent test rows remain committed and the sync acknowledgement remains accepted.

AI is outside this ingestion path entirely; a test installs an object that fails if touched and proves sync succeeds without accessing it.

## Files changed / added

Modified existing files:

- `.env.example`
- `app/api/router.py`
- `app/core/settings.py`
- `app/main.py`

Added runtime files:

- `app/api/sync.py`
- `app/auth/__init__.py`
- `app/auth/edge.py`
- `app/contracts/__init__.py`
- `app/contracts/sync.py`
- `app/contracts/sync_policy.py`
- `app/services/sync_ingestion.py`

Added contract/documentation files:

- `GLOBAL_SYNC_CONTRACT.md`
- `shared/contracts/GLOBAL_SYNC_CONTRACT.md`
- `shared/contracts/contract-manifest.json`
- `shared/schema/machine-session-report.schema.json`
- `shared/schema/evidence-manifest.schema.json`
- `shared/schema/incident-update.schema.json`
- `shared/schema/sync-envelope.schema.json`
- `shared/schema/sync-acknowledgement.schema.json`
- `scripts/generate_sync_schemas.py`

Added tests:

- `tests/sync_test_data.py`
- `tests/global/test_sync_contract.py`
- `tests/global/test_sync_ingestion.py`
- `tests/real_integration/test_sync_ingestion_postgres.py`

Added this report:

- `GLOBAL_PROMPTS_3_4_IMPLEMENTATION_REPORT.md`

## Validation results

### Prompt 3–4 focused tests

- `python -m pytest tests/global/test_sync_contract.py -q` — PASS, 10/10.
- `python -m pytest tests/global/test_sync_ingestion.py -q` — PASS, 21/21.
- New Prompt 3–4 total — PASS, 31/31.

### Global backend focused suite

- `python -m pytest tests/global -q` — PASS, 42/42.
- `python -m pytest tests/unit/test_settings.py -q` — PASS, 10/10.

### Import / migration / collection

- `python -c "import app.main"` — PASS.
- `alembic upgrade head --sql` — PASS; PostgreSQL transactional DDL generated through `0001_global_initial`.
- `python -m pytest --collect-only` — PASS, 284 tests collected.
- `tests/real_integration/test_sync_ingestion_postgres.py` — SKIPPED because the execution environment has no explicitly enabled live PostgreSQL integration service/`psycopg` runtime. The test is present and opt-in via `MINE_TRACE_RUN_REAL_POSTGRES_INTEGRATION=1` and `MINE_TRACE_TEST_POSTGRES_URL`.

### Full legacy repository suite

`python -m pytest -q --tb=no --junitxml=...`:

- total: 284
- passed: 201
- skipped: 23
- failed: 10
- errors: 50

The 60 non-passing tests are the already-known legacy integration tests that still instantiate SQLite `Settings(database_url="sqlite://...")`. PostgreSQL-only global settings correctly reject those URLs. No Prompt 3–4 focused test is failing.

## Remaining blockers / intentionally deferred work

- A live PostgreSQL service plus `psycopg` is required to execute the real database acceptance test rather than skip it.
- Legacy SQLite-era integration fixtures still need a later dedicated migration to PostgreSQL-compatible test infrastructure; PostgreSQL enforcement was not weakened to make them pass.
- Durable retry/index-job persistence is not added here; Prompt 4 only requires canonical commit to survive derived semantic failure. The post-commit boundary is in place for a later durable worker/outbox implementation.
- Fleet read APIs, sync-health/conflict read APIs and cross-machine semantic-search rework remain later prompts.
