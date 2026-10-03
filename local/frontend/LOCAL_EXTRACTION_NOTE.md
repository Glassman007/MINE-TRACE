# Local frontend extraction note

This folder is the extracted local frontend starting point from the uploaded React + TypeScript + Vite source.

It intentionally keeps the same-origin `/api/v1` client, TanStack Query setup, app shell, glass UI, machine/incidents/evidence/handover workflows, tests, and machine/media assets.

The current fleet-oriented `Machines` route/page is retained only because it is still wired into the existing router. It must be removed from primary local navigation or constrained to the configured machine during the local refocus. See `LOCAL_FURTHER_REQUIREMENTS.md` delivered alongside the ZIP for the complete remaining work.

No `node_modules`, `dist`, cache, or secret files are included.
