# MINE-TRACE GLOBAL — Prompt 7.5 FastEmbed Implementation Report

## Scope

Prompt 7.5 replaces the standard semantic embedding path with a local FastEmbed provider while preserving the existing provider abstraction, canonical PostgreSQL authority, durable post-commit indexing outbox, Qdrant-derived index, degraded capability behavior, and explicit rebuild mechanism.

No semantic architecture was redesigned.

## Dependency change

`pyproject.toml` now contains:

```toml
fastembed>=0.8.1,<0.9
```

The existing optional external embedding provider remains available, but it is no longer the development default.

The `openai` Python dependency remains only because the separately optional advisory AI provider still uses it. Standard semantic indexing/querying does not use OpenAI or require an OpenAI key.

## Default embedding configuration

`Settings` and `.env.example` now default to:

```text
MINE_TRACE_EMBEDDING_PROVIDER=fastembed
MINE_TRACE_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
MINE_TRACE_EMBEDDING_DIMENSION=384
```

`MINE_TRACE_EMBEDDING_API_KEY` remains optional for retained external providers and is blank for FastEmbed. FastEmbed itself requires no API secret.

Semantic search remains an optional capability controlled independently by `MINE_TRACE_SEMANTIC_SEARCH_ENABLED` and Qdrant configuration.

## Provider implementation

Added:

`app/integrations/embeddings/fastembed_local.py`

The provider:

- implements the existing `EmbeddingProvider` document/query/batch boundary;
- constructs one `fastembed.TextEmbedding` model per provider lifecycle;
- reuses that model for every document and query embedding;
- uses `passage_embed` for canonical semantic documents;
- uses `query_embed` for semantic queries;
- supports document batching;
- validates every returned vector against the configured dimension;
- reports local model initialization/inference failures through existing capability/observability state;
- performs no paid API call and stores no API secret.

`build_embedding_provider()` now selects FastEmbed when `embedding_provider=fastembed` while retaining the previous provider abstraction.

## Model and vector dimension

Configured model:

`BAAI/bge-small-en-v1.5`

Expected vector dimension:

`384`

The FastEmbed provider checks the model-reported embedding size during initialization. A model/configuration mismatch fails the semantic provider clearly instead of writing incompatible vectors.

Document and query vectors are also individually validated as 384-dimensional.

## Qdrant dimension safety

Application semantic initialization now calls the existing Qdrant collection initialization/compatibility path with the configured embedding dimension.

Behavior:

- missing collection: may be created at 384 dimensions;
- existing 384-dimensional compatible collection: reused;
- existing collection with another dimension, for example 768: not silently reused;
- mismatch: semantic runtime becomes `UNAVAILABLE` with `qdrant_collection_incompatible`;
- explicit Qdrant rebuild remains the supported mechanism for replacing derived vector state;
- canonical PostgreSQL records are never modified or deleted by this mismatch handling.

## Runtime lifecycle

When semantic search is enabled:

1. optional capability state is initialized;
2. the local FastEmbed provider/model is created once;
3. the provider is stored on `app.state.embedding_provider`;
4. Qdrant is stored on `app.state.qdrant_service`;
5. the collection is checked against the configured 384-dimensional vector size;
6. the existing `CanonicalEvidenceIndexingService` and durable coordinator reuse the same provider instance;
7. semantic query assembly reuses `app.state.embedding_provider` rather than recreating the model per request.

If Qdrant is already known to be unavailable at startup, the backend does not unnecessarily load/download the embedding model just to overwrite the clearer Qdrant degraded-state reason.

## Failure semantics

FastEmbed/model initialization failure:

- semantic retrieval becomes unavailable;
- embedding capability becomes unavailable;
- semantic indexing coordinator is not initialized;
- application startup is not failed by this optional integration;
- canonical PostgreSQL authority is unchanged;
- sync ingestion remains operational.

Embedding failure after a sync commit continues to use the Prompt 7 durable outbox/failure path and never rolls back canonical PostgreSQL data.

`/health` remains based on canonical database health; FastEmbed is not made a core health dependency.

## Existing Prompt 7 guarantees retained

The implementation preserves the existing tests and behavior proving:

- semantic work becomes processable only after canonical commit;
- transaction rollback creates no derived vector;
- embedding/Qdrant failure does not roll back canonical data;
- Qdrant payload references canonical IDs;
- ineligible evidence is skipped deterministically;
- the collection can be deleted and rebuilt from PostgreSQL;
- deleting Qdrant cannot delete canonical truth.

## Files changed

Modified:

- `.env.example`
- `pyproject.toml`
- `app/core/settings.py`
- `app/integrations/embeddings/__init__.py`
- `app/integrations/embeddings/factory.py`
- `app/main.py`
- `tests/unit/test_ml_ai_contract_boundaries.py`

Added:

- `app/integrations/embeddings/fastembed_local.py`
- `tests/unit/test_fastembed_embedding.py`
- `tests/global/test_fastembed_runtime_boundary.py`
- `GLOBAL_PROMPT_7_5_IMPLEMENTATION_REPORT.md`

## Validation executed

Focused FastEmbed/global regression command:

```text
pytest -o addopts='' -q \
  tests/global \
  tests/unit/test_fastembed_embedding.py \
  tests/unit/test_embedding_layer.py \
  tests/unit/test_qdrant_service.py \
  tests/unit/test_settings.py \
  tests/unit/test_ml_ai_contract_boundaries.py \
  tests/integration/test_app_boot.py
```

Result:

```text
113 passed
```

Additional validation:

```text
python -c "import app.main"
```

Result: PASS.

Full test collection after Prompt 7.5:

```text
312 tests collected
```

Full legacy repository run:

```text
229 passed
23 skipped
10 failed
50 errors
```

The same 60 non-green cases are the already-known SQLite-era integration tests that construct `Settings(database_url="sqlite://...")`. The PostgreSQL-only global runtime rejects them before their test bodies execute. Prompt 7.5 did not relax PostgreSQL authority to make legacy SQLite tests pass.

## Execution-environment limitation

The implementation sandbox could not download/install FastEmbed because outbound package resolution was unavailable. Therefore an actual ONNX inference run using the downloaded `BAAI/bge-small-en-v1.5` model could not be executed in this environment.

The FastEmbed adapter is tested through an injected FastEmbed-compatible local model double, including document/query operations, batching, 384-dimensional validation, one-time lifecycle reuse, initialization failure and Qdrant compatibility behavior. The declared runtime dependency will install FastEmbed in an environment with normal package access, at which point FastEmbed downloads/caches the model on first use and can run from that local cache thereafter.

No real API key or `.env` file was added.
