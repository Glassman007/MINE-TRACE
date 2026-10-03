"""Versioned API composition."""

from fastapi import APIRouter

from app.api.ai_insights import router as ai_insights_router
from app.api.components import router as components_router
from app.api.evidence import router as evidence_router
from app.api.evidence_bundle import router as evidence_bundle_router
from app.api.handovers import router as handovers_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.machines import router as machines_router
from app.api.overview import router as overview_router
from app.api.timeline import router as timeline_router
from app.api.verification import router as verification_router
from app.api.sessions import router as sessions_router
from app.api.return_to_service import router as return_to_service_router
from app.api.sync import router as sync_router
from app.api.semantic_search import router as semantic_search_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(overview_router)
api_v1_router.include_router(machines_router)
api_v1_router.include_router(components_router)
api_v1_router.include_router(evidence_router)
api_v1_router.include_router(timeline_router)
api_v1_router.include_router(incidents_router)
api_v1_router.include_router(verification_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(sync_router)
api_v1_router.include_router(return_to_service_router)
api_v1_router.include_router(semantic_search_router)
api_v1_router.include_router(handovers_router)
api_v1_router.include_router(evidence_bundle_router)
api_v1_router.include_router(ai_insights_router)
