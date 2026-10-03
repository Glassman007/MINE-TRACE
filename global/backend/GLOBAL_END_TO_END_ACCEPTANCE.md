# MINE-TRACE Global End-to-End Acceptance

Date: 2026-10-03

## Overall result

**FAIL — frontend runtime validation is blocked by unavailable npm dependencies in this execution environment.**

The implementation and backend/integration acceptance are complete, but the requested frontend `typecheck`, `lint`, `test`, and `build` gates cannot be truthfully marked PASS because the extracted frontend intentionally contains no `node_modules` and this environment cannot resolve packages from the npm registry (`EAI_AGAIN`). No tests were disabled or TypeScript errors suppressed to work around that limitation.

## Files changed

### Backend

- `app/api/incidents.py` — added a read-only incident maintenance-history endpoint.
- `app/schemas/incidents.py` — added generated/OpenAPI-compatible maintenance action response contracts.
- `openapi/global-backend.openapi.json` — regenerated after the read-contract addition.
- `tests/global/test_fleet_read_apis.py` — added positive GET/read-only maintenance-history coverage.
- `tests/global/test_global_end_to_end_acceptance.py` — added combined multi-machine sync/index/search acceptance coverage.

### Frontend

- `src/api/generated/openapi.json`
- `src/api/generated/types.ts`
- `src/api/incidents.ts`
- `src/app/routeMeta.ts`
- `src/app/router.tsx`
- `src/app/router.test.tsx`
- `src/components/layout/Sidebar.tsx`
- `src/pages/AIPage.tsx`
- `src/pages/AIPage.test.tsx`
- `src/pages/AnalyticsPage.tsx`
- `src/pages/AnalyticsPage.test.tsx`
- `src/pages/IncidentDetailPage.tsx`
- `src/pages/IncidentDetailPage.test.tsx`
- `src/pages/IncidentsPage.tsx`
- `src/pages/MachinesPage.tsx`
- `src/pages/MachinesPage.test.tsx`
- `src/pages/MaintenancePage.tsx`
- `src/pages/MaintenancePage.test.tsx`
- `src/pages/SearchPage.tsx`
- `src/pages/SearchPage.test.tsx`
- `src/pages/SyncConflictsPage.tsx`
- `src/pages/SyncConflictsPage.test.tsx`
- `src/pages/SyncPage.tsx`
- `src/pages/SyncPage.test.tsx`
- `src/pages/pages.css`

## Route / authority acceptance

**PASS**

Global routes implemented:

- `/`
- `/machines`
- `/machines/:machineId`
- `/incidents`
- `/incidents/:incidentId`
- `/maintenance`
- `/search`
- `/analytics`
- `/sync`
- `/sync/conflicts`
- `/ai`

Removed/not present:

- `/evidence/new`
- `/handover`
- `/handover/:packetId`

Production frontend static audit found no wrappers/routes for adding evidence, moving evidence, splitting incidents, starting/evaluating verification, return-to-service mutation, or handover mutation.

The frontend production API layer has only two analytical POST wrappers:

- `/api/v1/search/semantic`
- `/api/v1/ai/analyze`

Canonical synchronization submission remains a backend/edge-node responsibility, not a browser action.

## Page behavior acceptance

### Overview

**PASS by implementation/static contract; frontend runtime test blocked by npm dependency installation.**

Shows backend machine count, unresolved incident count, recent synchronized sessions and latest synchronization/conflict state. No health/productivity/risk score is fabricated.

### Machines

**PASS by implementation/static contract; frontend runtime test blocked.**

Uses server-side search/site/type/model/pagination filters and displays backend `latest_sync_received_at` rather than inventing online/offline state.

### Machine detail

**PASS by implementation/static contract; frontend runtime test blocked.**

Shows synchronized machine identity, components, sessions, incidents and last synchronization/report revision.

### Incidents

**PASS by implementation/static contract; frontend runtime test blocked.**

Uses exact machine/component/status/model/site/start/end backend filters and pagination.

### Incident detail

**PASS by backend test and implementation/static contract; frontend runtime test blocked.**

Read-only chain:

`incident -> evidence -> maintenance history -> verification history -> provenance/audit`

A real contract gap was found: the backend previously had no complete incident maintenance-history read endpoint. Added:

`GET /api/v1/incidents/{incident_id}/maintenance-actions`

This is GET-only and does not change maintenance state.

### Maintenance

**PASS by implementation/static contract; frontend runtime test blocked.**

Uses `/api/v1/maintenance-queue` canonical fields and deterministic backend ordering. No predictive priority/risk score is created.

### Semantic search

**PASS backend; frontend runtime test blocked.**

Flow remains:

`query -> local FastEmbed -> Qdrant candidates -> PostgreSQL hydration`

Results are explicitly labeled **Similar result** and the score is described as semantic similarity rather than confidence. Degraded embedding/Qdrant state is represented separately from canonical fleet state.

### Analytics

**PASS backend; frontend runtime test blocked.**

Uses relational `/api/v1/analytics/*` endpoints only. Qdrant/Groq outputs are not used for counts or trends.

### Sync / conflicts

**PASS backend; frontend runtime test blocked.**

Sync page distinguishes:

- canonical PostgreSQL
- Qdrant semantic capability
- local embedding capability
- Groq capability

Machine receipt/revision/recency and unresolved conflicts are displayed. Conflict detail renders existing and incoming revision metadata side-by-side and exposes no merge action.

### Groq AI

**PASS backend; frontend runtime test blocked.**

`POST /api/v1/ai/analyze` is invoked only from an explicit `Run Analysis` action. Canonical context is read-only and responses retain evidence references. Missing/unavailable Groq returns a degraded AI response without affecting canonical APIs.

## End-to-end backend/integration acceptance

Command:

```text
pytest -q -ra
```

Result:

- **322 collected**
- **299 passed**
- **23 skipped**
- **0 failed**
- **0 errors**

The 23 skipped cases were already-existing tests explicitly marked for real external PostgreSQL/Qdrant services via environment flags. No new test was skipped to obtain a green result.

New combined acceptance coverage in `test_global_end_to_end_acceptance.py` proves:

1. two independently identified machines synchronize structured sessions;
2. exact package redelivery returns the original acknowledgement and creates no duplicate canonical state;
3. a newer report revision preserves the previous report revision;
4. stable evidence identity is deduplicated across revisions;
5. incompatible same-revision content creates an explicit `sync_conflict`;
6. canonical evidence exists before any vector is written;
7. durable outbox processing indexes only after the synchronization transaction commits;
8. Qdrant ranking is hydrated back through PostgreSQL;
9. canonical payload and provenance are returned from PostgreSQL;
10. stale Qdrant evidence IDs are discarded.

Existing backend acceptance tests additionally prove:

- 100-machine routing by explicit identities rather than AI categorization;
- embedding failure leaves canonical ingestion committed;
- Qdrant failure leaves canonical ingestion committed;
- Qdrant deletion/rebuild leaves canonical truth intact;
- Groq missing key/provider failure degrades safely;
- malformed/failed Groq responses do not mutate incident state;
- semantic search ignores stale Qdrant IDs;
- semantic filtering is rechecked against canonical PostgreSQL data.

## OpenAPI / generated contracts

**PASS**

Commands:

```text
python scripts/export_openapi.py
npm run generate:api
```

Backend OpenAPI SHA-256 and frontend snapshot SHA-256 are identical:

```text
0226dc5a36d55bb0a5ea145e1d7e6c13a95e78e633004022d23bb19973d89b3b
```

All frontend API types remain generated from the frozen backend OpenAPI rather than hand-recreated.

Supplemental TypeScript syntax transpilation across every `src/**/*.ts` and `src/**/*.tsx` file using the installed TypeScript compiler: **PASS, zero syntax diagnostics**. This is not presented as a replacement for the blocked full project typecheck.

## Requested frontend commands — run last

### `npm run typecheck`

**FAIL / environment blocker**

The command stops before project type analysis because dependencies are unavailable:

```text
TS2688: Cannot find type definition file for 'vite/client'.
TS2688: Cannot find type definition file for 'node'.
```

### `npm run lint`

**FAIL / environment blocker**

```text
eslint: not found
```

### `npm test`

**FAIL / environment blocker**

```text
vitest: not found
```

### `npm run build`

**FAIL / environment blocker**

Stops at the same missing `vite/client` / Node type dependency bootstrap stage.

### Dependency restoration attempt

`npm ci` was attempted before the final gates. npm could not restore the intentionally omitted frontend dependencies because registry requests failed with DNS/network resolution errors such as:

```text
EAI_AGAIN registry.npmjs.org
```

A partial `node_modules` produced by the failed install is not included in the deliverable.

## Static frontend acceptance

**PASS**

- No forbidden local routes/actions found in production source.
- No absolute/localhost backend URLs found in production frontend API/page source.
- No hardcoded machine IDs, sites, demo fleet counts, fake online/offline state, risk score or fleet health score found in production page/API source.
- OpenAPI snapshot matches backend byte-for-byte.
- Only semantic search and explicit AI analysis use frontend POST wrappers.

## Remaining blockers

1. **Frontend dependency availability:** run `npm ci` in an environment with npm registry/package-cache access, then rerun all four frontend commands. Until those commands pass, overall end-to-end acceptance remains FAIL rather than being overstated.
2. **Real external-service tests:** the repository still contains opt-in real PostgreSQL/Qdrant tests. They require their services/environment flags; the deterministic in-process suite is green.
3. **Real Groq call:** automated tests use provider doubles and failure boundaries; a live Groq request requires a deployment-supplied `MINE_TRACE_GROQ_API_KEY`. No live secret is committed.
4. **Real FastEmbed model runtime:** deployment must have the configured model cached/downloadable. Failure is already isolated as a degraded semantic capability and does not affect canonical APIs.
