from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.ml_ai_observability import get_ml_ai_observability
from app.core.settings import get_settings
from app.db.session import get_db_session
from app.schemas.health import HealthResponse
from app.schemas.ml_ai_observability import MLAICapabilityReport
from app.services.ml_ai_capabilities import build_ml_ai_capability_report

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def health(session: Session = Depends(get_db_session)) -> HealthResponse:
    session.execute(text("SELECT 1"))
    return HealthResponse(status="ok", database="ok")


@router.get("/health/capabilities", response_model=MLAICapabilityReport)
def ml_ai_capabilities(request: Request) -> MLAICapabilityReport:
    """Report optional ML/AI operational readiness without affecting core health."""

    observability = getattr(
        request.app.state, "ml_ai_observability", get_ml_ai_observability()
    )
    return build_ml_ai_capability_report(
        app_state=request.app.state,
        settings=get_settings(),
        observability=observability,
    )
