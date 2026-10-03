from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.core.capabilities import CapabilityStatus
from app.core.ml_ai_observability import get_ml_ai_observability
from app.core.settings import get_settings
from app.db.session import get_db_session
from app.integrations.embeddings.factory import build_embedding_provider
from app.integrations.qdrant import QdrantService
from app.schemas.evidence_bundle import EvidenceBundleResponse
from app.schemas.semantic_history import SemanticHistoryFailure, SemanticHistoryResponse
from app.services.evidence_bundle import EvidenceBundleService, UnknownEvidenceBundleIncidentError
from app.services.semantic_history import SemanticHistoryService

router = APIRouter(prefix="/incidents", tags=["Evidence Bundle"])


class _UnavailableSemanticHistoryService:
    """Typed degraded semantic service used when optional runtime wiring is unavailable."""

    def __init__(self, failure: SemanticHistoryFailure) -> None:
        self._failure = failure

    def search_similar_history(self, evidence_id: UUID) -> SemanticHistoryResponse:
        del evidence_id
        return SemanticHistoryResponse(available=False, failure=self._failure)


def semantic_history_from_app(request: Request, session: Session | None = None):
    """Resolve semantic retrieval without granting Qdrant authority.

    Tests/deployments may inject a complete ``semantic_history_service``. Otherwise
    the request path assembles the accepted concrete SemanticHistoryService from
    the configured embedding provider and Qdrant service. Failure to assemble or
    reach optional semantic infrastructure degrades the bundle; it never blocks
    canonical reads.
    """

    injected = getattr(request.app.state, "semantic_history_service", None)
    if injected is not None:
        return injected

    settings = get_settings()
    observability = getattr(
        request.app.state, "ml_ai_observability", get_ml_ai_observability()
    )
    if not settings.semantic_search_enabled:
        return None

    capability = getattr(request.app.state, "semantic_retrieval_capability", None)
    if capability is not None and capability.status is CapabilityStatus.UNAVAILABLE:
        return _UnavailableSemanticHistoryService(
            SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE
        )

    if session is None:
        return _UnavailableSemanticHistoryService(
            SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE
        )

    embedding_provider = getattr(request.app.state, "embedding_provider", None)
    if embedding_provider is None:
        try:
            embedding_provider = build_embedding_provider(settings, observability=observability)
        except Exception:
            return _UnavailableSemanticHistoryService(
                SemanticHistoryFailure.EMBEDDING_UNAVAILABLE
            )

    qdrant = getattr(request.app.state, "qdrant_service", None)
    if qdrant is None:
        try:
            qdrant = QdrantService.from_settings(settings, observability=observability)
        except Exception:
            return _UnavailableSemanticHistoryService(
                SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE
            )

    return SemanticHistoryService(
        uow_factory_for_session(session),
        embedding_provider,
        qdrant,
        settings,
        observability=observability,
    )


@router.get("/{incident_id}/evidence-bundle", response_model=EvidenceBundleResponse)
def get_incident_evidence_bundle(
    incident_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
) -> EvidenceBundleResponse:
    service = EvidenceBundleService(
        uow_factory_for_session(session),
        get_settings(),
        semantic_history=semantic_history_from_app(request, session),
    )
    try:
        return service.build(incident_id)
    except UnknownEvidenceBundleIncidentError as exc:
        raise api_error(status_code=404, code="INCIDENT_NOT_FOUND", message=str(exc)) from exc
