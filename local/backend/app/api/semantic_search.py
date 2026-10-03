"""Configured-machine natural-language semantic search endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.integrations.embeddings.factory import build_embedding_provider
from app.integrations.qdrant import QdrantService
from app.schemas.semantic_search import SemanticSearchFailure, SemanticSearchRequest, SemanticSearchResponse
from app.services.semantic_search import NaturalLanguageSemanticSearchService, SemanticSearchConfigurationError

router = APIRouter(tags=["Semantic Search"])


@router.post("/semantic-search", response_model=SemanticSearchResponse)
def semantic_search(
    request: SemanticSearchRequest,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SemanticSearchResponse:
    if settings.local_machine_id is None:
        raise api_error(status_code=409, code="LOCAL_MACHINE_NOT_CONFIGURED", message="configured local machine identity is required")
    if not settings.semantic_search_enabled:
        return SemanticSearchResponse(
            available=False,
            failure=SemanticSearchFailure.SEMANTIC_SEARCH_DISABLED,
            reason="semantic search is disabled",
        )
    try:
        provider = build_embedding_provider(settings)
    except Exception as exc:
        return SemanticSearchResponse(
            available=False,
            failure=SemanticSearchFailure.EMBEDDING_UNAVAILABLE,
            reason=f"embedding_provider_unavailable:{type(exc).__name__}",
        )
    try:
        qdrant = QdrantService.from_settings(settings)
    except Exception as exc:
        return SemanticSearchResponse(
            available=False,
            failure=SemanticSearchFailure.SEMANTIC_INDEX_UNAVAILABLE,
            reason=f"qdrant_unavailable:{type(exc).__name__}",
        )
    try:
        return NaturalLanguageSemanticSearchService(
            uow_factory_for_session(session), provider, qdrant, settings
        ).search(request)
    except SemanticSearchConfigurationError as exc:
        raise api_error(status_code=409, code="LOCAL_MACHINE_NOT_CONFIGURED", message=str(exc)) from exc
