> **Historical extraction baseline:** this document records the pre-local-split frontend acceptance state. Prompts 11–14 supersede its fleet/old-overview endpoint descriptions. The current executable contract is `contracts/openapi.json`, with local UI rules in `FRONTEND_CONTRACT.md`.

# MINE-TRACE Frontend Production-Readiness Acceptance

**Audit date:** 2026-10-03  
**Scope:** Final frontend production-readiness pass only. No new product capability was added.  
**Release-signoff result:** **BLOCKED BY VALIDATION ENVIRONMENT**  
**Source/boundary audit result:** **PASS**

This audit reviews the completed MINE-TRACE frontend for responsive behavior, performance, accessibility, degraded states, backend-boundary compliance, visual consistency, and release validation. Where a check required a built browser application or a live seeded FastAPI backend, the result is explicitly marked **BLOCKED** rather than inferred.

---

## 1. Production-readiness corrections made during this pass

Only implementation-hardening changes were made; no new product workflow was introduced.

- The global animated background now falls back to the existing static treatment for `prefers-reduced-motion`, viewports at or below 520 px, Data Saver, or low-memory device hints. The video remains a single global `<video>` using `preload="metadata"`, `muted`, `playsInline`, and no route-local duplicate.
- The background and application layers were corrected so the glass-grid remains visible behind translucent panels without becoming the interaction layer.
- The global navigation changes to the mobile/tablet drawer at 1100 px, preventing the fixed desktop sidebar from consuming excessive width at 1024 px.
- Incident filters switch to a fluid compact layout before the desktop sidebar makes the content region too narrow at 1366/1440 widths.
- The modal confirmation primitive now has explicit title/description relationships, `aria-modal`, initial focus, and native modal focus containment through `<dialog>.showModal()`.
- The mobile drawer now traps interaction outside the drawer with `inert`, accepts Escape to close, focuses the navigation when opened, and restores focus to the menu button when closed.
- Reduced-motion-sensitive programmatic scrolling no longer uses smooth scrolling.
- Long evidence-timeline and audit entries use `content-visibility: auto` where supported, while large JSON payload inspectors remain collapsed by default.
- Incorrect primitive props found in Add Evidence were corrected and submission was switched away from uncaught `mutateAsync` use while preserving backend error state rendering.
- An undefined visual token (`--mt-bg-deep`) was removed in favor of the defined background token.

---

## 2. Implemented route and API mapping

| Frontend route / global surface | Backend APIs consumed | Notes |
|---|---|---|
| Global topbar | `GET /api/v1/health` | Backend/database availability only. It does not infer Qdrant, AI, sync, cloud, fleet, or machine health. |
| `/` | `GET /api/v1/overview`; small `GET /api/v1/incidents`; small `GET /api/v1/machines`; machine detail reads when needed for labels | Overview uses only backend counts/statuses plus backend collection previews. |
| `/machines` | `GET /api/v1/machines` | Backend filters: `offset`, `limit`, `search`, `site_name`, `machine_type`. |
| `/machines/:machineId` | `GET /api/v1/machines/{id}`; `GET /api/v1/machines/{id}/components`; `GET /api/v1/machines/{id}/timeline`; `GET /api/v1/incidents?machine_id=...` | Timeline remains backend ordered by original source time. |
| `/incidents` | `GET /api/v1/incidents`; machine reads for presentation names | Backend-supported incident filters only. |
| `/incidents/:incidentId` | Incident detail, evidence, audit, verification history/run, EvidenceBundle reads; move/split/start-verification/evaluate-due/AI POSTs | Corrective and verification mutations refetch authoritative server state. AI is explicit user action only. |
| `/evidence/new` | `GET /api/v1/machines`; `GET /api/v1/machines/{id}/components`; three accepted evidence-ingestion POST endpoints | No binary upload endpoint is assumed. |
| `/handover` | `POST /api/v1/handovers` | Creation only. There is intentionally no handover collection GET. |
| `/handover/:packetId` | `GET /api/v1/handovers/{id}`; `POST /api/v1/handovers/{id}/acknowledge`; incident/machine GETs where useful | Reload-safe known-packet detail. Acknowledgement does not close incidents. |

All browser application calls use the same-origin `/api/v1/...` namespace. The development-only Vite proxy targets the local FastAPI server; application components do not embed a backend hostname/port.

---

## 3. Responsiveness audit

### Source-level responsive matrix

The following is a **static CSS/layout audit**. A real-browser screenshot/overflow pass could not be completed because the dependency tree cannot be installed in this environment, so these entries are not represented as rendered-device proof.

| Target | Static audit | Relevant behavior |
|---|---|---|
| 1920 × 1080 | PASS | Desktop sidebar; content remains within the configured page maximum; multi-column command-center layouts remain enabled. |
| 1440 × 900 | PASS | Desktop sidebar; incident controls use the compact fluid breakpoint to avoid minimum-column overflow. |
| 1366 × 768 | PASS | Desktop sidebar; incident grids/filters use the compact layout before available content width becomes unsafe. |
| 1024 tablet | PASS | Drawer/navigation mode at `max-width: 1100px`; page receives the full tablet content width instead of a 272 px sidebar subtraction. |
| 768 tablet | PASS | Drawer mode; machine/page grids progressively reduce; narrow page modules stack or use fluid columns. |
| 430 mobile | PASS | Drawer mode; compact page padding; static background selected because viewport is ≤520 px; one-column content rules apply. |
| 390 mobile | PASS | Same constrained/mobile behavior as 430 px; video is not mounted. |

No production rule establishing page-level horizontal overflow was identified. The Incident Workspace section selector intentionally uses a **local** horizontally scrollable navigation strip on narrow widths; it does not require the document/body itself to scroll horizontally. Collections are primarily cards/lists rather than oversized visual tables.

### Animated background behavior

- Exactly one global `AppBackground` instance is mounted by `AppShell`.
- The MP4 is approximately **1.2 MB**, H.264, 800×450, 10 seconds.
- It uses `preload="metadata"` rather than eagerly downloading as application data.
- At ≤520 px, reduced motion, Data Saver, or detected low-memory conditions, the video element is not mounted and the static cyan/dark fallback remains.
- Background layers use `pointer-events: none` and remain behind the application shell.

**Rendered viewport verification:** BLOCKED — no runnable Vite/browser build is available in this environment because npm dependencies cannot be installed.

---

## 4. Performance audit

| Check | Result | Evidence from implementation |
|---|---|---|
| Background video duplicated per route | PASS | One `AppBackground` instance in the persistent parent `AppShell`; one MP4 source reference. |
| Route transitions remount global background | PASS | All product routes are children of the same `AppShell`. |
| Background constrained-device behavior | PASS | Reduced-motion/small-screen/Data Saver/low-memory static fallback. |
| Query caching | PASS | Shared TanStack Query client uses 15 s default `staleTime`, one retry for GETs, and disables refetch-on-window-focus by default. |
| Mutation retry loops | PASS | Global mutation retry is `0`. |
| AI executes because of rendering | PASS | AI is a mutation called only from the **Analyze Evidence** button; no effect calls it. |
| Evaluate-due continuously POSTs | PASS | It is an explicit mutation action; no timer/effect invokes it. |
| JSON inspectors expanded by default | PASS | Evidence/audit/raw/provenance inspectors use collapsed `<details>` patterns. |
| Long exact timeline/audit rendering | PASS (source) | Timeline remains server ordered; entries use `content-visibility: auto`/intrinsic containment where supported. |
| Uncontrolled request loops | PASS (source) | Query parameters form stable query keys; effects found during audit adjust UI state/scroll/focus rather than fire mutation requests. |

The source does not implement route-level code splitting. That is an optimization opportunity rather than a proven release blocker for the current MVP, and adding it was outside this no-new-feature audit.

---

## 5. Accessibility audit

| Requirement | Result | Notes |
|---|---|---|
| Keyboard navigation | PASS (source) | Native buttons/links/inputs are used; mobile drawer gets keyboard focus and supports Escape. |
| Visible focus states | PASS | Global `:focus-visible` treatment covers buttons, links, inputs, textareas, selects and tabindex elements; specialized citation/mode controls also have visible focus. |
| Dialog focus containment | PASS (source) | Confirmation uses native modal `<dialog>.showModal()`; initial focus is on Cancel; title/description are ARIA-related. |
| Mobile drawer focus containment | PASS (source) | Main frame is `inert` while open; focus enters navigation and is restored to the trigger on close. |
| ARIA labels/states | PASS (source) | Navigation triggers expose expanded/control state; selected mode/component/incident section controls expose pressed state; icon-only controls audited for labels. |
| Form labels | PASS (source) | Add Evidence and filter controls use visible/associated labels rather than placeholder-only identity. |
| Table semantics | N/A | The dense collections are implemented as semantic cards/articles/definition groups rather than pretending div grids are HTML tables. No production `<table>` requiring header/cell remediation was found. |
| Status not color-only | PASS | Human-readable status text is rendered alongside visual treatment. |
| Contrast over background | PASS (token audit) | Static token ratios against `#010509`: main text 19.15:1, muted 11.54:1, subtle 6.69:1, accent 10.50:1, danger 8.42:1, warning 11.91:1, success 12.19:1. Panels/readability overlays further darken the video beneath text. |
| `prefers-reduced-motion` | PASS | Global motion suppression and static-background path are implemented. |

**Automated axe/browser accessibility scan:** BLOCKED because the frontend cannot be built/launched in this runtime.

---

## 6. Error and degraded-state audit

No reviewed state intentionally produces an empty application shell. Errors are rendered through reusable error states or workflow-specific conflict/degraded panels.

| State | Result | Frontend behavior |
|---|---|---|
| Backend unavailable | PASS (source) | Topbar reports backend unavailable; route queries render error states instead of fabricated data. |
| 404 | PASS (source/tests present) | Detail routes surface not-found states, including incident/handover. |
| 409 | PASS (source/tests present) | Structured state conflicts are displayed, including correction/verification conflicts and `HANDOVER_ALREADY_ACKNOWLEDGED`. |
| 422 | PASS (transport/source) | Structured FastAPI validation errors are parsed instead of displaying `[object Object]`. |
| 500 | PASS (transport/source) | Generic HTTP/server failure has a readable fallback error; no fake data is substituted. |
| Empty machines | PASS (source/tests present) | Legitimate empty-state UI. |
| Empty incidents | PASS (source/tests present) | Legitimate empty-state UI. |
| Overview zero counts | PASS (source/tests present) | Zero is displayed as backend data rather than hidden/replaced. |
| Missing optional metadata | PASS (source/tests present) | Presentation fallbacks use available identifiers; missing metadata is not guessed. |
| EvidenceBundle `PARTIAL` | PASS (source/tests present) | Deterministic evidence remains visible with incomplete/degraded enrichment described. |
| `INSUFFICIENT_EVIDENCE` | PASS (source/tests present) | First-class bundle state, not a blank module. |
| Semantic retrieval not configured | PASS | Bundle-local message; no global Qdrant availability claim. |
| Semantic retrieval failed | PASS | States that semantic retrieval is unavailable while deterministic evidence remains available. |
| AI `FALLBACK` | PASS (source/tests present) | States AI analysis is unavailable and retains deterministic evidence plus the structured fallback reason. |

The HTTP client prefers the backend structured `error.code` / `error.message` envelope, retains `detail` compatibility, and handles validation-array details.

---

## 7. Backend-boundary compliance audit

Production-source scans found **no hardcoded UUID-shaped machine, component, or incident identifiers** and no production import of test fixtures/demo data.

### No fabricated product capability found

The production frontend does **not** implement or claim authoritative support for:

- machine health or fleet health;
- uptime, availability, productivity, risk score or failure probability;
- global synchronization state or cloud state;
- fake incident resolution/closure controls;
- binary attachment upload, recording, playback or speech-to-text;
- a global Qdrant-availability indicator;
- a global AI-provider-availability indicator;
- machine CRUD;
- component CRUD;
- direct generic incident status editing.

Occurrences of phrases such as “machine health” or “binary upload” found in production source are explicit **negative boundary notices** explaining that those capabilities are not inferred/available, not implemented status values.

### Hardcoding scan

- UUID-shaped machine IDs in production: **none found**.
- UUID-shaped component IDs in production: **none found**.
- UUID-shaped incident IDs in production: **none found**.
- Backend counts used as production seed constants: **none found**.
- Production imports of test fixtures: **none found**.
- Browser source calls to `localhost:8000` / `127.0.0.1:8000`: **none found**. (`vite.config.ts` contains the development proxy target, which is configuration rather than browser application code.)
- Binary-upload browser APIs (`FormData`, file inputs, MediaRecorder, getUserMedia, SpeechRecognition): **none found** in production source.
- Machine/component write endpoints: **none found**.
- Handover collection GET: **none found**.

Intentional backend capability gaps such as no handover-history collection, no binary attachment upload, no machine-health endpoint, and no machine/component CRUD are **not frontend bugs** and remain correctly unrepresented.

---

## 8. Visual-language audit

**PASS by source/style review.**

The application retains the established MINE-TRACE visual language:

- near-black machine-command-center base;
- cyan glass-grid ambient video/static fallback;
- readable dark translucent glass surfaces rather than opaque white/solid viewport coverings;
- restrained cyan borders/highlights and status accents;
- technical typography and monospaced technical identifiers;
- no rainbow gradients, giant neon typography, fake circular KPI progress rings, or route-local decorative animation;
- the video remains visible in gaps between modules on capable desktop/tablet viewports.

No new decorative animation was added during this audit.

---

## 9. Static validation performed successfully

After the final production-hardening changes:

- **PASS** — TypeScript/TSX syntax transpile check across **60** source files using the available global TypeScript parser.
- **PASS** — all relative TypeScript/TSX imports resolve.
- **PASS** — CSS parse/static-variable audit; an undefined background variable found during the audit was corrected.
- **PASS** — package/TypeScript configuration JSON parsing.
- **PASS** — production UUID scan.
- **PASS** — browser direct-backend-host scan.
- **PASS** — binary upload/media-recording API scan.
- **PASS** — production fixture/test-import scan.
- **PASS** — one global AppBackground/video source only.
- **PASS** — no mutation invocation found inside React effects.

These checks are useful source-level evidence but do **not** replace the requested real dependency-aware compiler/test/build runs.

---

## 10. Required npm validation results

All requested commands were actually invoked after the final source changes.

| Command | Result | Exact blocker |
|---|---|---|
| `npm run lint` | **BLOCKED / exit 127** | `eslint: not found` |
| `npm run typecheck` | **BLOCKED / exit 1** | TypeScript cannot resolve `vite/client` and `node` type definitions because dependencies are absent. |
| `npm run test` | **BLOCKED / exit 127** | `vitest: not found` |
| `npm run build` | **BLOCKED / exit 1** | Same absent `vite/client` and Node typings before Vite can build. |

A registry probe failed with:

```text
EAI_AGAIN getaddrinfo registry.npmjs.org
```

The local `node_modules` directory contains only temporary TypeScript build-info files; it does not contain the dependency tree required for lint/typecheck/test/build. The audit did not create dependency shims or fake a passing release run.

---

## 11. Playwright / E2E validation

### Playwright

No Playwright dependency, configuration, or existing E2E suite is present in this frontend. The instruction was to run it **if Playwright exists**, so no Playwright command was fabricated or added during this audit.

### Seeded FastAPI E2E

The required seeded-backend browser validation could not be executed in this runtime:

```text
GET http://127.0.0.1:8000/api/v1/health -> connection refused / HTTP 000
```

No runnable seeded backend source/archive is present in the working container. Therefore the following required real end-to-end journeys remain **BLOCKED**, not failed by observed frontend behavior:

- Overview
- Machines collection
- Machine detail
- Timeline filters
- Incidents collection
- Incident detail
- Verification
- EvidenceBundle
- AI fallback/validated handling where provider behavior is available
- Evidence ingestion
- Handover creation and acknowledgement

The repository has unit/component/API tests covering these major workflows, including degraded states and mutation/refetch behavior, but they cannot be executed until Vitest and its dependencies are installed.

---

## 12. Genuine remaining limitations and release blockers

### Release blockers

1. **The real npm dependency tree is unavailable in this environment.** Registry DNS fails with `EAI_AGAIN`, so `lint`, full `typecheck`, Vitest, and production `build` cannot be completed.
2. **No seeded FastAPI backend is running or materialized in the execution environment.** The required seeded-backend E2E journey cannot be performed.
3. **Because the app cannot be built/launched here, real browser viewport/overflow and automated accessibility validation cannot be completed.** The source-level responsive/accessibility review passes, but it is not a substitute for release-device/browser evidence.

### Non-blocking / intentional limitations

These are backend/product boundaries rather than frontend defects:

- no handover-history collection endpoint;
- no binary attachment upload/download/audio-recording API;
- no machine-health/fleet-health API;
- no global synchronization-status API;
- no machine or component CRUD;
- AI and semantic retrieval may be unavailable and have first-class degraded states.

---

## 13. Release decision

The code-level production-readiness audit found no remaining known frontend boundary violation that should be hidden by fake data or invented capability. However, the requested release-signoff commands and seeded-backend E2E cannot be completed in the current execution environment.

**Frontend-ready: NO**

**Exact blockers:** unavailable npm dependencies/registry access; no runnable seeded FastAPI backend; consequently no real production build/test/lint/typecheck run and no browser/E2E viewport validation can be signed off here.
