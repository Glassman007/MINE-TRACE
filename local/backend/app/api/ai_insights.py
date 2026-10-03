"""Explicit advisory AI-analysis action endpoint.

This module is the only HTTP transport that invokes the optional AI provider.
GET/read endpoints never call the provider. The provider receives only the
already-built deterministic EvidenceBundle and has no canonical or Qdrant
mutation capability.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.api.evidence_bundle import semantic_history_from_app
from app.core.ml_ai_observability import get_ml_ai_observability
from app.core.settings import get_settings
from app.db.session import get_db_session
from app.integrations.llm.factory import build_ai_provider
from app.schemas.ai_result import AIAnalysisResult
from app.services.ai_analysis_pipeline import AIAnalysisPipeline
from app.services.evidence_bundle import EvidenceBundleService, UnknownEvidenceBundleIncidentError

router = APIRouter(prefix="/incidents", tags=["AI Insights"])


def _ai_provider_from_app(request: Request):
    injected = getattr(request.app.state, "ai_provider", None)
    if injected is not None:
        return injected
    observability = getattr(
        request.app.state, "ml_ai_observability", get_ml_ai_observability()
    )
    return build_ai_provider(get_settings(), observability=observability)


@router.post("/{incident_id}/ai-analysis", response_model=AIAnalysisResult)
def analyze_incident_evidence(
    incident_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
) -> AIAnalysisResult:
    """Run optional advisory analysis only after an explicit POST action."""

    try:
        bundle = EvidenceBundleService(
            uow_factory_for_session(session),
            get_settings(),
            semantic_history=semantic_history_from_app(request, session),
        ).build(incident_id)
    except UnknownEvidenceBundleIncidentError as exc:
        raise api_error(status_code=404, code="INCIDENT_NOT_FOUND", message=str(exc)) from exc

    # The pipeline can only consume the sealed bundle. It cannot receive the
    # session/UoW, repositories, canonical mutation services, or Qdrant writes.
    observability = getattr(
        request.app.state, "ml_ai_observability", get_ml_ai_observability()
    )
    return AIAnalysisPipeline(
        _ai_provider_from_app(request), observability=observability
    ).analyze(bundle)
