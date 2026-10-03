"""Versioned API composition for the extracted global baseline."""

from fastapi import APIRouter

from app.api.ai_insights import router as ai_insights_router
from app.api.ai import router as fleet_ai_router
from app.api.components import router as components_router
from app.api.fleet import router as fleet_router
from app.api.maintenance import router as maintenance_router
from app.api.analytics import router as analytics_router
from app.api.evidence_bundle import router as evidence_bundle_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.machines import router as machines_router
from app.api.overview import router as overview_router
from app.api.sync import router as sync_router
from app.api.search import router as search_router
from app.api.verification import router as verification_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(overview_router)
api_v1_router.include_router(fleet_router)
api_v1_router.include_router(machines_router)
api_v1_router.include_router(components_router)
api_v1_router.include_router(incidents_router)
api_v1_router.include_router(verification_router)
api_v1_router.include_router(maintenance_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(evidence_bundle_router)
api_v1_router.include_router(ai_insights_router)
api_v1_router.include_router(fleet_ai_router)
api_v1_router.include_router(search_router)
api_v1_router.include_router(sync_router)
