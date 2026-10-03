import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import install_exception_handlers
from app.api.health import router as health_router
from app.api.router import api_v1_router
from app.core.capabilities import CapabilityState, CapabilityStatus, initialize_capability_states
from app.core.logging import configure_logging
from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import get_settings
from app.db.session import SessionLocal
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.integrations.embeddings import build_embedding_provider
from app.integrations.qdrant import (
    QdrantAvailability,
    QdrantCollectionCompatibilityError,
    QdrantService,
    QdrantUnavailableError,
)
from app.services.semantic_indexing import CanonicalEvidenceIndexingService, DurableSemanticIndexingCoordinator

settings = get_settings()
configure_logging(settings)
logger = logging.getLogger(__name__)


def initialize_semantic_runtime(_app: FastAPI) -> None:
    """Initialize optional local-embedding/Qdrant runtime without owning app health.

    Any FastEmbed or Qdrant failure is converted to explicit optional-capability
    state. Canonical PostgreSQL startup/health and sync ingestion are not raised
    from this boundary.
    """

    _app.state.semantic_indexing_coordinator = None
    if not settings.semantic_search_enabled:
        return

    semantic_state = getattr(_app.state, "semantic_retrieval_capability", None)
    if (
        semantic_state is not None
        and semantic_state.status is CapabilityStatus.UNAVAILABLE
        and semantic_state.reason == "qdrant_unavailable"
    ):
        # There is no usable semantic path while Qdrant is unreachable. Avoid
        # downloading/loading the local model merely to overwrite the clearer
        # Qdrant degraded-state reason. Canonical PostgreSQL remains available.
        return

    try:
        embedding = build_embedding_provider(
            settings, observability=_app.state.ml_ai_observability
        )
        _app.state.embedding_provider = embedding
    except Exception as exc:
        reason = "embedding_model_initialization_failed"
        _app.state.embedding_provider_capability = CapabilityState(
            CapabilityStatus.UNAVAILABLE, reason
        )
        _app.state.semantic_retrieval_capability = CapabilityState(
            CapabilityStatus.UNAVAILABLE, reason
        )
        logger.warning(
            "semantic_embedding_runtime_not_initialized",
            extra={"error_type": type(exc).__name__},
        )
        return

    try:
        qdrant = QdrantService.from_settings(
            settings, observability=_app.state.ml_ai_observability
        )
        _app.state.qdrant_service = qdrant
        if settings.embedding_dimension is None:
            raise RuntimeError("embedding_dimension is required for semantic runtime")
        collection = qdrant.initialize_collection(
            vector_size=settings.embedding_dimension
        )
        if collection.availability is QdrantAvailability.UNAVAILABLE:
            raise QdrantUnavailableError(
                collection.reason or "Qdrant collection is unavailable"
            )
        if not collection.compatible:
            raise QdrantCollectionCompatibilityError(
                "configured Qdrant collection is incompatible with embedding model: "
                f"expected_dimension={settings.embedding_dimension}, "
                f"actual_dimension={collection.actual_vector_size}, "
                f"reason={collection.reason or 'unknown'}"
            )

        def semantic_uow_factory():
            return SQLAlchemyUnitOfWork(SessionLocal)

        indexer = CanonicalEvidenceIndexingService(
            semantic_uow_factory,
            embedding,
            qdrant,
            observability=_app.state.ml_ai_observability,
        )
        _app.state.semantic_indexing_service = indexer
        _app.state.semantic_indexing_coordinator = DurableSemanticIndexingCoordinator(
            SessionLocal, indexer
        )
    except QdrantCollectionCompatibilityError as exc:
        _app.state.semantic_retrieval_capability = CapabilityState(
            CapabilityStatus.UNAVAILABLE, "qdrant_collection_incompatible"
        )
        logger.warning(
            "semantic_qdrant_collection_incompatible",
            extra={"error_type": type(exc).__name__},
        )
    except Exception as exc:
        _app.state.semantic_retrieval_capability = CapabilityState(
            CapabilityStatus.UNAVAILABLE, "qdrant_unavailable"
        )
        logger.warning(
            "semantic_indexing_runtime_not_initialized",
            extra={"error_type": type(exc).__name__},
        )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("application_starting", extra={"environment": settings.environment})
    _app.state.ml_ai_observability = MLAIObservability()
    initialize_capability_states(_app, settings)
    initialize_semantic_runtime(_app)
    yield
    logger.info("application_stopping")


OPENAPI_TAGS = [
    {"name": "Health", "description": "Core application and canonical PostgreSQL health."},
    {"name": "Overview", "description": "Authoritative PostgreSQL-derived fleet counts."},
    {"name": "Machines", "description": "Controlled machine identity reads."},
    {"name": "Components", "description": "Controlled component identity reads."},
    {"name": "Fleet", "description": "Exact relational fleet overview and synchronized session reads."},
    {"name": "Maintenance", "description": "Deterministic queue derived only from synchronized relational facts."},
    {"name": "Analytics", "description": "Counts, rates and trends computed from canonical PostgreSQL."},
    {"name": "Incidents", "description": "Synchronized fleet incident reads and evidence history."},
    {"name": "Verification", "description": "Read-only verification outcomes synchronized from edge machines."},
    {"name": "Evidence Bundle", "description": "Deterministic evidence-bundle read model."},
    {"name": "AI Insights", "description": "Explicit read-only Groq fleet analysis grounded in canonical evidence."},
    {"name": "Semantic Search", "description": "Fleet-wide semantic similarity retrieval with PostgreSQL hydration."},
    {"name": "Synchronization", "description": "Authenticated transactional edge-to-global package ingestion."},
]

app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)
install_exception_handlers(app)

# Canonical versioned API.
app.include_router(api_v1_router)
# Backward-compatible operational health probe. No domain functionality lives here.
app.include_router(health_router)
