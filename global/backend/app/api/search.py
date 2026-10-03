from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.session import get_db_session
from app.schemas.semantic_search import FleetSemanticSearchRequest, FleetSemanticSearchResponse, SemanticSearchState
from app.services.fleet_semantic_search import FleetSemanticSearchService

router = APIRouter(prefix="/search", tags=["Semantic Search"])


@router.post("/semantic", response_model=FleetSemanticSearchResponse)
def semantic_search(payload: FleetSemanticSearchRequest, request: Request, session: Session = Depends(get_db_session)) -> FleetSemanticSearchResponse:
    settings = get_settings()
    if not settings.semantic_search_enabled:
        return FleetSemanticSearchResponse(state=SemanticSearchState.DISABLED, reason="semantic_search_disabled")
    embedding = getattr(request.app.state, "embedding_provider", None)
    qdrant = getattr(request.app.state, "qdrant_service", None)
    if embedding is None:
        return FleetSemanticSearchResponse(state=SemanticSearchState.DEGRADED, reason="embedding_unavailable")
    if qdrant is None:
        return FleetSemanticSearchResponse(state=SemanticSearchState.DEGRADED, reason="semantic_index_unavailable")
    return FleetSemanticSearchService(session, embedding, qdrant, settings).search(payload)
