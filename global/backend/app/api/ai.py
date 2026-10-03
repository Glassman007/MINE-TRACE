from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.ml_ai_observability import get_ml_ai_observability
from app.core.settings import get_settings
from app.db.session import get_db_session
from app.integrations.llm.factory import build_ai_provider
from app.schemas.fleet_ai import FleetAIAnalysisRequest, FleetAIAnalysisResponse
from app.services.fleet_ai_analysis import FleetAIAnalysisService
from app.services.fleet_semantic_search import FleetSemanticSearchService

router = APIRouter(prefix="/ai", tags=["AI Insights"])


@router.post("/analyze", response_model=FleetAIAnalysisResponse)
def analyze_fleet(payload: FleetAIAnalysisRequest, request: Request, session: Session = Depends(get_db_session)) -> FleetAIAnalysisResponse:
    settings = get_settings()
    provider = getattr(request.app.state, "ai_provider", None)
    if provider is None:
        provider = build_ai_provider(settings, observability=getattr(request.app.state, "ml_ai_observability", get_ml_ai_observability()))

    semantic = None
    embedding = getattr(request.app.state, "embedding_provider", None)
    qdrant = getattr(request.app.state, "qdrant_service", None)
    if embedding is not None and qdrant is not None:
        semantic = FleetSemanticSearchService(session, embedding, qdrant, settings)

    return FleetAIAnalysisService(session, provider, model=settings.ai_model, semantic_service=semantic).analyze(payload)
