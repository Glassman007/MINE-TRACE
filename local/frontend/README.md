# MINE-TRACE Local Frontend

React + TypeScript + Vite local-node UI for one backend-configured MINE-TRACE machine.

## Foundation scope

This increment contains only:

- token-based industrial glass visual system;
- ambient fixed MP4 application background with reduced-motion fallback;
- responsive/collapsible application shell;
- route scaffolding for the accepted frontend architecture;
- TanStack Query provider and a same-origin backend health query;
- reusable visual primitives;
- neutral loading/skeleton layout placeholders.

It intentionally contains no fabricated machines, incidents, counts, seed identities, sync state, AI/provider state, health/risk scores, uptime, availability, or predictive-maintenance values.

## API connectivity

Browser code uses relative `/api/v1/...` URLs. During development Vite proxies `/api` to `http://127.0.0.1:8000`. Production should serve the frontend and API through the same origin or a reverse proxy.

## Commands

```bash
npm install
npm run dev
npm run build
npm run typecheck
npm run lint
```


## Generated API types

The portable backend OpenAPI snapshot lives at `contracts/openapi.json`. Generate/check the TypeScript snapshot with:

```bash
npm run api:types
npm run api:types:check
```

The generator is dependency-free and produces `src/api/generated/openapi.ts` directly from the backend schema snapshot.
