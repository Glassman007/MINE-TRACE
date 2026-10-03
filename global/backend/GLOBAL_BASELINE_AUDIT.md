# MINE-TRACE Global Baseline Audit

## Scope

Stabilization only. No global synchronization ingestion, final fleet schema, or global frontend screens were implemented in this pass.

## Dangling imports removed

Backend extraction leftovers removed from runtime composition/exports:

- `app.api.evidence`
- `app.api.timeline`
- `app.api.handovers`
- `app.models.handover`
- `app.schemas.ingestion`
- `app.services.ingestion`
- `app.services.recurrence`
- `app.services.incident_correction`
- handover repository/UoW exports and implementations

The central incident API retains read endpoints but no longer imports or exposes the deleted local incident-correction mutation service.

Frontend local-only routes/navigation removed:

- `/evidence/new`
- `/handover`
- `/handover/:packetId`

## Local-only responsibilities identified for later removal/adaptation

- SQLite-first runtime settings/session behavior
- local verification execution/return-to-service authority
- local lifecycle assumptions
- same-machine semantic-history behavior
- local EvidenceBundle/timeline assumptions retained as reusable source material
- local wording in OpenAPI/capability descriptions

## Reusable modules identified

- FastAPI application/dependency structure
- machine/component/incident read foundations
- SQLAlchemy repository/UoW patterns
- Qdrant client abstraction
- embedding provider abstraction
- LLM provider/fallback/validation boundaries
- semantic document/indexing foundations
- frontend shell, background, primitives, query infrastructure, machine/incident presentation

## Validation

Backend:

- `python -c "import app.main"` — PASS
- `python -m pytest --collect-only -q` — PASS after removing retained tests' references to deleted handover persistence
- static `app.*` import inspection — PASS, zero missing internal modules

Frontend:

- `npm run typecheck` — BLOCKED by absent `node_modules` (`vite/client` and Node type definitions unavailable)
- `npm run build` — BLOCKED for the same dependency-installation reason
- `npm ci --ignore-scripts` was attempted but dependency installation did not complete in the execution environment
- static route/import cleanup completed; no deleted Add Evidence/Handover page imports remain in the three requested routing/navigation files

## Remaining expected failures / deferred work

- PostgreSQL runtime conversion and clean global schema are intentionally deferred to Prompts 1–2.
- Legacy tests still exercise SQLite/local semantics and are expected to require replacement/adaptation as global persistence work proceeds.
- Frontend typecheck/build requires declared npm dependencies to be installed; this is an environment/dependency availability blocker, not a remaining extraction import.
