import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import install_exception_handlers
from app.api.health import router as health_router
from app.api.router import api_v1_router
from app.core.capabilities import initialize_capability_states
from app.core.logging import configure_logging
from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import get_settings

settings = get_settings()
configure_logging(settings)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("application_starting", extra={"environment": settings.environment})
    _app.state.ml_ai_observability = MLAIObservability()
    if settings.demo_mode:
        from app.demo.seed import seed_demo
        summary = seed_demo(settings)
        logger.info("demo_seed_ready", extra={"machine_id": summary.machine_id, "sync_state": summary.sync_state})
    initialize_capability_states(_app, settings)
    yield
    logger.info("application_stopping")


OPENAPI_TAGS = [
    {"name": "Health", "description": "Core application and SQLite health."},
    {"name": "Overview", "description": "Configured local-machine canonical overview; no fleet or inferred health semantics."},
    {"name": "Machines", "description": "Configured local-machine identity reads plus deprecated compatibility collection access."},
    {"name": "Components", "description": "Controlled component identity reads."},
    {"name": "Evidence", "description": "Controlled authoritative evidence ingestion."},
    {"name": "Timeline", "description": "Exact historical evidence timelines."},
    {"name": "Incidents", "description": "Incident state, evidence, audit and controlled correction."},
    {"name": "Verification", "description": "Deterministic persisted verification workflows."},
    {"name": "Sessions", "description": "Configured-machine operating sessions and immutable close reports."},
    {"name": "Sync", "description": "Durable edge-to-central outbox status and measured transport state."},
    {"name": "Return to Service", "description": "Deterministic auditable configured-machine clearance policy."},
    {"name": "Semantic Search", "description": "Derived local semantic recall with canonical SQLite hydration."},
    {"name": "Handover", "description": "Historical shift handover snapshots and acknowledgement."},
    {"name": "Evidence Bundle", "description": "Deterministic evidence-bundle read model."},
    {"name": "AI Insights", "description": "Advisory, evidence-bundle-only AI analysis."},
]

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)
install_exception_handlers(app)
@app.get("/api/v1/health", include_in_schema=False)
def demo_health():
    return {"status": "ok", "database": "ok"}
# Canonical versioned API.
app.include_router(api_v1_router)
# Backward-compatible operational health probe. No domain functionality lives here.
app.include_router(health_router)
