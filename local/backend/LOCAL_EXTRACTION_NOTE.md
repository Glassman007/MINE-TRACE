# Local backend extraction note

This folder is the extracted local backend+ML starting point from the uploaded `latest_backend` source.

It intentionally keeps the deterministic FastAPI/SQLite domain, API routes, migrations, tests, Qdrant integration, embedding abstraction, semantic services, optional LLM boundary, and semantic benchmark assets.

It does **not** claim that the final local architecture is complete. See `LOCAL_FURTHER_REQUIREMENTS.md` delivered alongside the ZIP for the remaining work, especially operating sessions, deterministic session reports, durable sync outbox/conflicts, return-to-service, an offline embedding provider, and the new local APIs.

No live `.env`, local database, virtual environment, cache directory, or credential file is included.
