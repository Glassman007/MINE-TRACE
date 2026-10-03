"""Deterministic incident verification transport APIs."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.domain.lifecycle import InvalidIncidentTransition
from app.schemas.verification import (
    DueVerificationEvaluationResponse,
    VerificationRunResponse,
    VerificationRunsResponse,
)
from app.services.verification import (
    UnknownVerificationIncidentError,
    UnknownVerificationRunError,
    VerificationAlreadyActiveError,
    VerificationConfigurationMismatchError,
    VerificationError,
    VerificationRunView,
    VerificationService,
)

router = APIRouter(tags=["Verification"])


def _service(session: Session, settings: Settings) -> VerificationService:
    return VerificationService(settings, uow_factory_for_session(session))


def _response(view: VerificationRunView) -> VerificationRunResponse:
    return VerificationRunResponse(
        id=view.id,
        incident_id=view.incident_id,
        verification_rule_id=view.verification_rule_id,
        rule_identifier=view.rule_identifier,
        rule_name=view.rule_name,
        rule_type=view.rule_type,
        window_minutes=view.window_minutes,
        result=view.result,
        started_at=view.started_at,
        window_ends_at=view.window_ends_at,
        completed_at=view.completed_at,
        evidence_event_ids=list(view.evidence_event_ids),
    )


@router.post("/incidents/{incident_id}/verification", response_model=VerificationRunResponse, status_code=201)
def start_verification(
    incident_id: UUID,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VerificationRunResponse:
    try:
        return _response(_service(session, settings).start_verification(incident_id))
    except UnknownVerificationIncidentError as exc:
        raise api_error(status_code=404, code="INCIDENT_NOT_FOUND", message=str(exc)) from exc
    except (InvalidIncidentTransition, VerificationAlreadyActiveError) as exc:
        raise api_error(status_code=409, code="VERIFICATION_STATE_CONFLICT", message=str(exc)) from exc
    except VerificationConfigurationMismatchError as exc:
        raise api_error(status_code=409, code="VERIFICATION_CONFIGURATION_CONFLICT", message=str(exc)) from exc


@router.get("/incidents/{incident_id}/verifications", response_model=VerificationRunsResponse)
def list_verifications(
    incident_id: UUID,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VerificationRunsResponse:
    try:
        views = _service(session, settings).list_for_incident(incident_id)
    except UnknownVerificationIncidentError as exc:
        raise api_error(status_code=404, code="INCIDENT_NOT_FOUND", message=str(exc)) from exc
    return VerificationRunsResponse(incident_id=incident_id, runs=[_response(view) for view in views])


@router.post("/verifications/evaluate-due", response_model=DueVerificationEvaluationResponse)
def evaluate_due_verifications(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> DueVerificationEvaluationResponse:
    return DueVerificationEvaluationResponse(
        evaluated=[_response(view) for view in _service(session, settings).evaluate_due()]
    )


@router.get("/verifications/{run_id}", response_model=VerificationRunResponse)
def get_verification(
    run_id: UUID,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> VerificationRunResponse:
    try:
        return _response(_service(session, settings).get_run(run_id))
    except UnknownVerificationRunError as exc:
        raise api_error(status_code=404, code="VERIFICATION_RUN_NOT_FOUND", message=str(exc)) from exc
    except VerificationError as exc:
        raise api_error(status_code=409, code="VERIFICATION_CONFLICT", message=str(exc)) from exc
