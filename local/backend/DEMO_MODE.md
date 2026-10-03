# MINE-TRACE Local Demo Mode

Demo mode is an explicit presentation-only path. It seeds one local machine (`EXC-204`, Hydraulic Excavator, North Ridge Mine) and runs the same SQLite/domain workflows used by normal operation.

## Configure

Create a local `.env` (never commit or package it):

```text
MINE_TRACE_DEMO_MODE=true
MINE_TRACE_DATABASE_URL=sqlite:///./mine_trace_demo.db
MINE_TRACE_AI_ENABLED=true
MINE_TRACE_AI_PROVIDER=groq
MINE_TRACE_AI_MODEL=qwen/qwen3.8-27b
MINE_TRACE_GROQ_API_KEY=
```

Demo mode automatically selects the demo machine, a demo-only deterministic local embedding used to exercise the Qdrant path without a model download, a local Qdrant location, and an explicit demo return-to-service policy. `DEMO_MODE=false` retains the normal FastEmbed/local-node behavior.

## Seed / reset

Startup seeds idempotently when demo mode is enabled. Manual commands:

```bash
python -m app.demo.seed
python -m app.demo.seed --reset
```

`--reset` is refused unless demo mode is enabled and is refused in production.

The seeded story is: operating session → hydraulic observation → deterministic incident linking → derived semantic history candidate → maintenance evidence → persisted verification → return-to-service evaluation → immutable session report/EvidenceManifest → durable SyncEnvelope → central revision conflict → current unresolved cooling work.

Groq remains explicit-action advisory analysis only and is never invoked during demo seeding.

## Frontend presentation routes

With the local frontend pointed at this backend, demo mode fills the normal local-node screens through the real APIs:

- `/` — This Machine overview and demo-mode marker
- `/components` — backend components with presentation-only schematic coordinates
- `/history` — canonical maintenance evidence only
- `/incidents` — canonical incident state
- `/search` — derived semantic retrieval, clearly labelled `Semantic`
- `/session` — active session plus the immutable report referenced by the latest outbox package
- `/return-to-service` — deterministic policy state and exact blockers
- `/sync` — persisted outbox/conflict/measured transport facts

The frontend contains no Groq credential. The only hardcoded browser demo values are centralized presentation coordinates and a suggested search phrase; identity, status, counts, incidents, evidence, sessions, safety state and synchronization facts continue to come from the backend.
