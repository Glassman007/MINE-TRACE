# MINE-TRACE MVP Backend

This repository contains the accepted MINE-TRACE MVP backend with authoritative SQLite persistence, deterministic evidence/incident/verification/handover workflows, optional semantic retrieval, advisory LLM orchestration, and read-only frontend-facing collection APIs.

## Runtime and stack

- Python 3.12 is the intended runtime.
- FastAPI exposes the HTTP API.
- Pydantic v2 + `pydantic-settings` provide typed API/configuration boundaries.
- SQLAlchemy 2.x is the persistence layer.
- Alembic owns schema evolution.
- SQLite is the authoritative local database.
- `qdrant-client` is reserved for optional semantic retrieval only.
- pytest is the test runner; pytest-asyncio is available if later APIs become asynchronous.

## Architectural boundaries

### SQLite is authoritative

All durable facts belong in SQLite. Qdrant must never be the system of record for evidence, raw payloads, provenance, timeline ordering, incident state, verification state, handover state, or audit history.

Raw source data is append-preserved. Later evidence must not silently overwrite earlier historical evidence.

Compound state changes must be performed inside database transactions so an operation either commits completely or rolls back completely.

### Qdrant is a derived semantic index

The semantic-history architecture includes an optional Qdrant-derived index that stores embeddings and identifiers pointing back to authoritative SQLite records when the integration is configured. Qdrant is not authoritative and may be unavailable at runtime. Qdrant failure, indexing failure, or embedding failure degrades semantic retrieval only; deterministic backend behavior continues.

### LLMs are advisory

Advisory LLM analysis is implemented behind an optional provider boundary. It can return validated summaries, explanations, or structured observations when a provider is available, and returns deterministic `FALLBACK` behavior when provider execution or validation fails. It may not directly mutate incident status, verification result, owner, severity, due state, evidence, audit history, or closure state.

### Deterministic service ownership

Deterministic application services own evidence identity, ingestion, incident linking, recurrence, incident correction, verification, handover, auditing, `EvidenceBundle` construction, and AI-output validation. Handover and deterministic `EvidenceBundle` construction are implemented backend workflows, not frontend responsibilities.

### Configuration, not hardcoding

Business thresholds are typed settings. Linking windows, history lookback, semantic `top_k`, semantic score threshold, verification windows, and evidence limits must not be embedded as magic values inside service code.

### MVP scope discipline

The project should not introduce generalized queues, event buses, distributed transaction systems, generic plugin frameworks, or other infrastructure unless a concrete MVP requirement needs them.

## Project layout

```text
backend/
  app/
    api/             # HTTP routes only; thin transport layer
    domain/          # Domain types/rules without infrastructure dependencies
    db/              # SQLAlchemy base, engine and session lifecycle
    models/          # Authoritative SQLAlchemy persistence records
    repositories/    # Persistence abstractions
    services/        # Deterministic application use-cases
    schemas/         # Pydantic request/response contracts
    integrations/
      qdrant/        # Optional derived semantic index adapter
      embeddings/    # Optional embedding provider adapter
      llm/           # Optional advisory LLM adapter
    core/            # Settings and cross-cutting logging
    main.py           # FastAPI application composition
  migrations/        # Alembic migration environment and revisions
  tests/
    unit/
    integration/
  pyproject.toml
  alembic.ini
  .env.example
  README.md
```

Dependency direction should flow inward: transport/integrations depend on application/domain contracts, while deterministic domain/service code must not require Qdrant, embeddings, or an LLM to execute.

## Setup

Create a Python 3.12 virtual environment, then install the project with development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
pip install -e '.[dev]'
cp .env.example .env
```

Apply migrations:

```bash
alembic upgrade head
```

Run the API:

```bash
uvicorn app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","database":"ok"}
```

Run tests:

```bash
pytest
```

Check migration drift:

```bash
alembic check
```

## Authoritative persistence schema

Alembic revision `4ab3b3b323b6` creates the authoritative tables; later revisions extend historical context/attachments, verification, handover snapshots, and nullable asset presentation metadata. Current head: `d81f9c3a72e4`.

```text
machines
components
evidence_events
evidence_attachments
context_snapshots
incidents
incident_evidence_links
incident_audit_events
verification_rules
verification_runs
verification_evidence
handover_packets
handover_items
sync_changes
sync_conflicts
```

The evidence identity constraint is enforced by SQLite as `UNIQUE(source_type, original_source_record_id)`. Timeline, incident-link, verification, and handover access paths have explicit indexes. Runtime SQLite connections enable `PRAGMA foreign_keys=ON`. See `app/models/README.md` for persistence assumptions and deliberately unresolved vocabularies.

## Current baseline behavior

Application bootstrapping, `GET /health`, canonical domain contracts, authoritative persistence, repository/UoW primitives, controlled ingestion, exact historical timeline retrieval, deterministic incident linking/correction, recurrence handling, restart-safe deterministic verification, append-only audit, handover snapshots, optional semantic history, deterministic EvidenceBundle construction, and the advisory LLM orchestration boundary now exist. The health endpoint verifies SQLite connectivity but deliberately does not require Qdrant, an embedding provider, or an LLM to be available.

## Repository and transaction layer

Persistence access is exposed through repository protocols in `app/repositories/interfaces.py`, with SQLAlchemy implementations in `app/repositories/sqlalchemy.py`. Repositories do not commit transactions and do not implement incident, recurrence, verification, handover, or correction business rules.

`SQLAlchemyUnitOfWork` owns one SQLAlchemy `Session` and all repositories for one transaction. Callers explicitly invoke `commit()`; exceptions and normal context-manager exit with uncommitted work roll back. `flush()` is available for compound operations that need parent rows persisted before dependent rows while remaining in the same transaction.

Destructive operations are intentionally restricted: the evidence repository exposes no deletion primitive, the audit repository exposes neither update nor delete, and incident-evidence links expose `deactivate(...)` rather than delete. Historical audit and context ORM guards from the persistence layer remain in force.


## Controlled MVP ingestion

The backend exposes exactly three ingestion request contracts and routes: machine events, maintenance records, and human observations. Source type is assigned by the backend rather than accepted from callers. Ingestion resolves existing machine/component identities, preserves raw payload/provenance/original timestamps, writes evidence plus optional fixed-dimension historical context and optional attachment metadata atomically, and reuses existing evidence for duplicate `(source_type, original_source_record_id)` submissions. Deterministic incident linking and recurrence recording run inside the same ingestion transaction after authoritative evidence persistence. See `INGESTION_PIPELINE_REPORT.md`.


## Exact historical timeline retrieval

`GET /api/v1/machines/{machine_id}/timeline` returns authoritative evidence ordered by `EvidenceEvent.original_timestamp` with the evidence ID as the deterministic tie-breaker. It supports optional `component_id`, `from`, and `to` filters; the bounds are inclusive. `ingestion_timestamp` is returned for provenance/diagnostics but is never used for historical ordering.

Controlled ingestion normalizes aware source timestamps to the same UTC instant before SQLite persistence so differing source offsets cannot corrupt event-time ordering. Timeline responses expose timestamps explicitly as UTC.

Historical context uses exactly five dimensions: `shift`, `location`, `machine_operating_state`, `workload`, and `environment`. Every dimension contains `value`, `quality` (`KNOWN`, `UNKNOWN`, or `STALE`), and a source-provided `freshness_basis`. Context snapshots remain immutable through the repository/ORM path and are attached to the evidence-time event rather than refreshed from current machine state.

Attachment metadata is persisted with evidence ID, attachment type, storage reference, MIME type, file size, checksum, and creation time. Audio can be represented as attachment metadata; no speech-to-text or media processing is implemented. See `TIMELINE_CONTEXT_ATTACHMENTS_REPORT.md`.

## Deterministic incident linking

Newly ingested canonical evidence is now deterministically associated with an incident
inside the ingestion transaction. Eligibility uses only authoritative SQLite state and
typed configuration: same machine, exact component identity, configured canonical
event-type compatibility, and a bounded `original_timestamp` window. No semantic
similarity, embeddings, Qdrant, ML, or LLM participates in this decision.

Configuration lives under the `MINE_TRACE_INCIDENT_LINKING_*` settings documented in
`.env.example`. When multiple incidents qualify, stable source-time/ID tie-breaks make
the selection reproducible. Every created association persists its rule identifier,
reason and controlled relationship type and appends audit events.

Read-only inspection endpoints:

- `GET /api/v1/incidents/{incident_id}`
- `GET /api/v1/incidents/{incident_id}/evidence`

See `INCIDENT_LINKING_REPORT.md` for the exact rule and implementation decisions.

## Deterministic incident-association correction

Wrong evidence-to-incident associations are corrected by `IncidentCorrectionService`.
Source evidence is never deleted as a correction mechanism. `move_evidence` moves an
association to an explicit existing incident; `split_incident` creates a new `OPEN`
incident and moves explicitly named evidence. Old links are deactivated, not deleted,
and unlink/link/split audit records are committed in the same Unit of Work. Any failure
rolls the entire correction back. See `INCIDENT_CORRECTION_REPORT.md`.


## Deterministic recurrence handling

Duplicate replay remains defined exclusively by `(source_type, original_source_record_id)` and returns the existing evidence before linking or recurrence behavior runs. A distinct source record that deterministically matches an existing incident is persisted as a new raw evidence event and linked with relationship type `RECURRENCE`. The service appends `RECURRENCE_RECORDED`; `VERIFYING` and `VERIFIED` incidents transition to `RECURRED`, while `OPEN` remains `OPEN` because `OPEN -> RECURRED` is not an allowed lifecycle transition.

No occurrence counter is persisted. `RecurrenceService.reconstruct_occurrences(...)` deterministically rebuilds current occurrence state from active `RELATED` and `RECURRENCE` evidence links ordered by `EvidenceEvent.original_timestamp`; `VERIFICATION` links are excluded. See `RECURRENCE_REPORT.md`.


## Deterministic verification

`VerificationService` implements the frozen lifecycle `OPEN -> VERIFYING -> VERIFIED`,
with recurrence transitions `VERIFYING/VERIFIED -> RECURRED` and reverification
`RECURRED -> VERIFYING`. `OPEN -> VERIFIED` remains forbidden by the canonical
lifecycle validator.

The MVP rule is `NO_EVENT`: a verification succeeds only when no active recurrence
evidence has an `EvidenceEvent.original_timestamp` inside the persisted verification
window. The rule definition persists its configured `window_minutes`; every run freezes
`started_at`, absolute `window_ends_at`, and `completed_at`. Evaluation reads only
SQLite state, so process restart or runtime setting changes do not restart or move an
in-flight window. Successful `NO_EVENT` runs have no fabricated verification-evidence
row; recurrence failures persist the actual triggering evidence in
`verification_evidence`.

Verification endpoints:

- `POST /api/v1/incidents/{incident_id}/verification`
- `GET /api/v1/incidents/{incident_id}/verifications`
- `POST /api/v1/verifications/evaluate-due`
- `GET /api/v1/verifications/{run_id}`

See `VERIFICATION_REPORT.md`.

## Append-only incident audit and shift handover

Incident audit actions remain a controlled `IncidentAuditAction` enum. Historical audit rows are append-only in normal application behavior: the audit repository exposes only `add`, `get`, and `list_for_incident`, while ORM update/delete attempts raise `AppendOnlyAuditViolation`.

Audit retrieval:

```http
GET /api/v1/incidents/{incident_id}/audit
```

Shift handover endpoints:

```http
POST /api/v1/handovers
GET /api/v1/handovers/{id}
POST /api/v1/handovers/{id}/acknowledge
```

The MVP handover packet includes every incident whose persisted status at packet creation is `OPEN`, `VERIFYING`, or `RECURRED`. Because the requested API contains no machine/shift/filter input, no narrower scope is invented. Each `HandoverItem` stores immutable snapshots of severity, owner, status, due state, and due time. Later incident changes never rewrite those snapshot fields.

Acknowledgement sets `handover_packets.acknowledged_at` and appends `HANDOVER_ACKNOWLEDGED` to every included incident in the same transaction. It does not change incident status, close the incident, or mark it `VERIFIED`. No acknowledgement actor field is invented because the current specification does not define one.

Alembic revision `c6f3e92a4d11` adds the five handover snapshot columns. They are nullable at the schema level only to migrate legacy rows without fabricating historical values; new service-created handovers always write a status snapshot and faithfully copy the other fields, including legitimate `NULL` values.

## Optional semantic historical retrieval

Semantic retrieval is a derived capability only. `SemanticHistoryService` embeds canonical evidence content, searches a `QdrantSemanticIndex`, receives canonical evidence IDs, and hydrates every returned ID from authoritative SQLite before returning it. Same-machine and optional same-component scope are re-checked after hydration, so stale or incorrectly filtered Qdrant references cannot become canonical results.

The configuration foundation uses `MINE_TRACE_SEMANTIC_SEARCH_ENABLED`, `MINE_TRACE_QDRANT_URL`, `MINE_TRACE_QDRANT_API_KEY`, `MINE_TRACE_QDRANT_COLLECTION`, `MINE_TRACE_QDRANT_TIMEOUT_SECONDS`, `MINE_TRACE_QDRANT_DISTANCE`, `MINE_TRACE_EMBEDDING_PROVIDER`, `MINE_TRACE_EMBEDDING_MODEL`, and optional `MINE_TRACE_EMBEDDING_API_KEY`. `MINE_TRACE_SEMANTIC_TOP_K` defaults to `5`; `MINE_TRACE_SEMANTIC_SCORE_THRESHOLD` intentionally defaults to `None` and should be set only after benchmarking the selected embedding model. No Qdrant URL, provider, model, API credential, or embedding vector dimensionality is hardcoded.

Optional capability readiness uses `AVAILABLE`, `DISABLED`, and `UNAVAILABLE`. Startup performs only a best-effort Qdrant connectivity probe when semantic search is enabled and sufficiently configured. Probe failure marks semantic retrieval unavailable and does not fail canonical backend startup. The Qdrant service layer can discover, initialize, and validate the dedicated collection and can operate on derived vector points, but application startup still does not make collection readiness authoritative and semantic workflow wiring remains optional.

The embedding layer now defines separate `embed_document`, `embed_query`, and batch-document contracts, plus deterministic semantic-document extraction from string values already present in canonical `canonical_payload`. Raw source payloads and provenance are not promoted into semantic text, and numeric-only telemetry is not converted into invented prose. Semantic documents reuse the canonical `evidence_id`; no second semantic identity is generated.

The normal local embedding configuration is the pinned offline `fastembed_local` provider using `BAAI/bge-small-en-v1.5` at 384 dimensions. Demo mode may select the isolated deterministic `demo_hash` provider only to exercise the derived-index presentation path without a model download. Qdrant stores canonical `evidence_id` references plus filter metadata and remains disposable/derived. The configured collection dimension is validated against the embedding provider. Qdrant similarity/distance scores are ranking values only and must never be presented as model confidence, factual probability, or canonical evidence strength.

## Deterministic EvidenceBundle

`GET /api/v1/incidents/{incident_id}/evidence-bundle` constructs a read-only
bundle with primary incident evidence, deterministic exact history, optional
semantic history, verification context, immutable evidence-time context snapshots,
and a provenance index.

Bundle sufficiency is deterministic: at least one active canonical SQLite
incident evidence event is required for `READY`. Semantic history is enrichment
only and can never create canonical sufficiency. If configured semantic retrieval
fails while canonical primary evidence remains usable, the bundle returns
`PARTIAL` rather than failing the canonical request.

Exact history is selected using same machine, exact component identity, exact
canonical event type, strictly earlier `original_timestamp`, and the configured
`MINE_TRACE_HISTORY_LOOKBACK_DAYS`. Global evidence deduplication uses
`evidence_id` with priority primary > exact > semantic.


## Advisory AI/LLM orchestration boundary

`POST /api/v1/incidents/{incident_id}/ai-analysis` is the explicit AI action. It loads the incident through deterministic EvidenceBundle construction, includes exact canonical history and optional Qdrant-backed semantic history, and only then passes that sealed `EvidenceBundle` to the provider-neutral `AIProvider`. The provider/guard pipeline receives no database session, repository, UnitOfWork, incident mutation service, verification service, handover service, or Qdrant write capability.

The endpoint returns the stable `AIAnalysisResult` envelope: `VALIDATED_AI` only after schema, bundle-local citation, and claim-policy validation; otherwise `FALLBACK` constructed solely from deterministic bundle data. AI configuration is independent of Qdrant and uses `MINE_TRACE_AI_ENABLED`, `MINE_TRACE_AI_PROVIDER`, `MINE_TRACE_AI_MODEL`, `MINE_TRACE_GROQ_API_KEY`, and `MINE_TRACE_AI_TIMEOUT_SECONDS`. Missing or disabled provider configuration is a valid fallback state and never blocks the canonical backend.

No GET endpoint executes the AI provider. Incident GET, evidence GET, timeline GET, EvidenceBundle GET, and health GET remain read-only/model-free. Semantic retrieval may run while building an EvidenceBundle, but Qdrant candidates are canonically hydrated before entering the bundle and never gain canonical authority.

Validation is deterministic and ordered: schema validation, citation-ID validation, then claim-policy validation. The policy rejects authoritative root-cause, maintenance-certification, repair/failure guarantees, maintenance instructions, incident transitions, unsupported verification/recurrence outcomes, and owner/severity changes. Provider failure or any guard rejection produces deterministic `FALLBACK`; no rejected model text is reused as trusted output.

## Versioned FastAPI transport layer

The public domain API is composed under `/api/v1`. Route handlers own transport concerns only: request parsing, response projection, HTTP status codes and mapping service/domain exceptions into the shared structured error envelope. Business decisions remain in services.

Error responses use the shape:

```json
{
  "error": {
    "code": "INCIDENT_NOT_FOUND",
    "message": "unknown incident: ...",
    "details": null
  },
  "detail": "unknown incident: ..."
}
```

`detail` is retained for compatibility with earlier clients; new callers should consume `error.code`, `error.message`, and `error.details`.

Controlled identity reads are intentionally read-only at this stage: machine/component creation semantics were not specified by the MVP, so the API does not invent administrative creation/deletion workflows. Machine records expose nullable `display_name`, `asset_code`, `machine_type`, `manufacturer`, `model`, `site_name`, and `site_area`; component records expose nullable `display_name`, `component_type`, `manufacturer`, and `model`. Existing upgraded rows remain valid with `NULL` metadata, while the deterministic demo seed supplies meaningful presentation values. `asset_code`, when present, is unique.

Frontend-facing read APIs are repository-backed and derive totals from SQLite:

- `GET /api/v1/machines?offset=&limit=&search=&site_name=&machine_type=`
- `GET /api/v1/machines/{machine_id}`
- `GET /api/v1/machines/{machine_id}/components`
- `GET /api/v1/components/{component_id}`
- `GET /api/v1/incidents?offset=&limit=&machine_id=&status=&severity=&owner_ref=&due_state=`
- `GET /api/v1/incidents/{incident_id}`
- `GET /api/v1/overview`

Machine ordering is deterministic by non-null `display_name ASC`, then ID, with unnamed machines ordered after named machines. Incident collection ordering is `updated_at DESC`, then incident ID. The overview contains only authoritative machine/component/incident counts and every canonical `IncidentStatus` key, including zero-count statuses; it does not fabricate health, online, availability, or risk KPIs.

There are no normal DELETE endpoints for evidence, audit history, historical context, verification history, or handover history.

Evidence ingestion returns `evidence_id` plus `idempotent_replay`; source identity and replay detection remain owned by `IngestionService`, not by the route handler.

The AI endpoint is advisory only. The API constructs the deterministic EvidenceBundle first and passes only that bundle to `AIOrchestrationService`; it exposes no persistence/session/UoW handle to the provider and has no state mutation path.

## Deterministic local demo mode

Demo records are isolated behind `MINE_TRACE_DEMO_MODE=true`. When enabled, FastAPI startup idempotently seeds one local machine (`EXC-204`, Hydraulic Excavator, North Ridge Mine) plus its seven presentation components and exercises the real SQLite domain workflows: evidence ingestion, deterministic incident linking, maintenance evidence, persisted verification, return-to-service, session close/report/EvidenceManifest generation, durable SyncEnvelope queuing, and a persisted central revision conflict.

Manual demo setup/reset uses the same seeder:

```bash
python -m app.demo.seed
python -m app.demo.seed --reset
```

`--reset` is permitted only with demo mode enabled and is refused in production. Re-running without reset is idempotent and does not duplicate domain records. Demo fixtures and presentation coordinates are centralized under `app/demo/`; normal `DEMO_MODE=false` operation keeps the production local-node configuration. Semantic demo data is still indexed through the embedding/Qdrant abstraction and canonically hydrated from SQLite; Qdrant remains disposable derived state. See `DEMO_MODE.md` for setup details.

### Optional AI provider adapter

The current optional hosted provider adapter is `groq`, implemented with the native Groq Python SDK. The model remains configuration-driven through `MINE_TRACE_AI_MODEL`. The adapter receives only the deterministic `EvidenceBundle`, exposes no tools or canonical mutation capability, requests JSON output, and returns an explicitly `UNVALIDATED` structured candidate. Structural parsing is not citation/factual/policy validation; the guard layer remains a separate stage. `MINE_TRACE_GROQ_API_KEY` must come from the local environment/deployment secret and must never be committed or exposed to the frontend. Groq is explanation/analysis only; local embeddings remain the vector provider.

### Deterministic AI-analysis fallback

The provider-neutral `AIAnalysisPipeline` distinguishes `VALIDATED_AI` from `FALLBACK`. Fallback construction is handled by `DeterministicFallbackBuilder`, which has no provider, repository, database, or Qdrant dependency and projects only already-typed `EvidenceBundle` facts. It is used for disabled/unconfigured/unavailable AI, timeout/provider failure, malformed model output, unknown citations, prohibited claims, and `INSUFFICIENT_EVIDENCE`. Insufficient evidence short-circuits before any provider call.

Fallback output can expose canonical primary/exact evidence, original timestamps, canonical payload/provenance, deterministic verification context, and semantic-enrichment availability. If semantic retrieval failed (including Qdrant unavailability), fallback reports semantic enrichment as `UNAVAILABLE` and does not fabricate semantic matches. Provider error text or rejected model content is not reused as fallback analysis.


## ML/AI observability and capability reporting

Optional ML/AI infrastructure has a separate operational report at
`GET /api/v1/health/capabilities` (also available as `/health/capabilities`).
This endpoint does not redefine core application/database health and does not
mutate canonical state.

Each optional capability is reported as exactly one of:

- `AVAILABLE` — verified by a live probe or successful runtime operation;
- `DISABLED` — intentionally disabled by configuration;
- `UNAVAILABLE` — configured but missing, unreachable, unverified, or failed.

Environment variables alone are never sufficient to mark Qdrant, embeddings,
or the AI provider `AVAILABLE`. Qdrant reporting verifies connectivity and that
the configured semantic collection exists. Embedding reporting verifies the
provider using a synthetic non-canonical probe. AI reporting uses a non-
generative provider/model probe when the adapter supports it; otherwise it
remains unavailable until runtime availability is actually observed.

The process-local observability snapshot exposes coarse operational signals
only: Qdrant connectivity/search failures and search latency, embedding
failures, indexing failures, stale Qdrant-reference drops, AI provider
timeouts/errors, validation-stage rejections, and deterministic fallback
reasons. These values are operational telemetry, not domain facts and are not
persisted into canonical tables.

Logging redacts fields whose names indicate API keys, authorization, secrets,
tokens, passwords, payloads, provenance, or prompts. ML/AI telemetry must not
log evidence bodies, provider credentials, authorization headers, or model
prompt/response text.

## Semantic-quality benchmark

The production-shaped semantic retrieval benchmark lives under `benchmarks/semantic_quality/`.
It uses an isolated PostgreSQL schema and isolated Qdrant collections while exercising the
configured embedding model, real Qdrant search, and canonical hydration through the accepted
semantic services. It does not benchmark a standalone cosine-similarity substitute and does
not select a production similarity threshold automatically.

See `benchmarks/semantic_quality/README.md` for dataset coverage, safety rules, metrics, and
reproducible execution commands.
