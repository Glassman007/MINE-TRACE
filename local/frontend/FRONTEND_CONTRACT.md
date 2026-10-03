# MINE-TRACE Local Frontend Contract

**Scope:** one configured local machine.  
**Transport source:** `contracts/openapi.json`, copied from the accepted local backend and generated into `src/api/generated/openapi.ts`.

## Authority boundaries

- SQLite/backend domain services remain canonical.
- The browser never chooses an authoritative machine identity; it reads `GET /api/v1/machines/current`.
- Qdrant/embeddings are optional derived semantic facilities.
- AI is advisory and is invoked only by an explicit POST action.
- Return-to-service, verification, incident state, synchronization facts and counts are backend-owned.
- The browser must not invent health percentages, uptime, productivity, predictions, safety state, sync success, component status or IDs.

## Connectivity

Application code uses only same-origin relative `/api/v1/...` paths. The development-only Vite proxy may target the local FastAPI server. Application source must not call `http://localhost:8000` or `http://127.0.0.1:8000` directly, and normal deployment does not require CORS.

## Local identity and navigation

Primary navigation is:

- `/` — **This Machine** overview;
- `/components` and `/components/:componentId` — schematic component navigation/exact component history;
- `/incidents` and `/incidents/:incidentId` — configured-machine incident memory;
- `/evidence/new` — controlled ingestion for the configured machine;
- `/handover` — local handover workflow.

The legacy `/machines/:machineId` detail route is retained only as a compatibility deep link. It first resolves `/machines/current` and rejects any route ID that differs from the configured machine instead of switching context.

## Local API modules

The frontend has modules for overview, current-machine identity, components, incidents, evidence, verification, handover, EvidenceBundle, sessions, semantic search, return-to-service, sync status, health and AI.

Important reads include:

```text
GET  /api/v1/overview
GET  /api/v1/machines/current
GET  /api/v1/machines/current/components
GET  /api/v1/sessions/active
GET  /api/v1/return-to-service
GET  /api/v1/sync/status
GET  /api/v1/health
```

Natural-language semantic search is the backend-defined POST read operation:

```text
POST /api/v1/semantic-search
```

AI remains an explicit-action mutation:

```text
POST /api/v1/incidents/{incident_id}/ai-analysis
```

## Component presentation

The backend currently provides component identity but no authoritative physical anchor coordinates. `/components` therefore uses an explicitly **schematic** card layout and existing machine artwork. It does not fabricate physical positions or red/yellow/green component state.

Component detail combines exact canonical timeline, active incident associations, canonical maintenance/repair evidence, recurrence state and persisted verification runs. Semantic similarity is not mixed into the exact-history view.

## Generated types

Do not hand-copy backend Pydantic response definitions.

```text
npm run api:types
npm run api:types:check
```

The generator reads `contracts/openapi.json`; browser code never imports Python modules or requires an external `shared/` directory at runtime.
