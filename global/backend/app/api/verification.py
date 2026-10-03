"""Read-only synchronized verification history APIs."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.db.session import get_db_session
from app.schemas.verification import VerificationRunResponse, VerificationRunsResponse
from app.services.verification import (
    UnknownVerificationIncidentError,
    UnknownVerificationRunError,
    VerificationQueryService,
    VerificationRunView,
)

router = APIRouter(tags=["Verification"])


def _service(session: Session) -> VerificationQueryService:
    return VerificationQueryService(uow_factory_for_session(session))


def _response(view: VerificationRunView) -> VerificationRunResponse:
    return VerificationRunResponse(
        id=view.id,
        incident_id=view.incident_id,
        session_id=view.session_id,
        source_machine_id=view.source_machine_id,
        verification_rule_id=view.verification_rule_id,
        rule_identifier=view.rule_identifier,
        rule_name=view.rule_name,
        rule_type=view.rule_type,
        window_minutes=view.window_minutes,
        result=view.result,
        started_at=view.started_at,
        window_ends_at=view.window_ends_at,
        completed_at=view.completed_at,
        original_timestamp=view.original_timestamp,
        source_report_revision=view.source_report_revision,
        outcome_payload=view.outcome_payload,
        evidence_event_ids=list(view.evidence_event_ids),
    )


@router.get("/incidents/{incident_id}/verifications", response_model=VerificationRunsResponse)
def list_verifications(
    incident_id: UUID,
    session: Session = Depends(get_db_session),
) -> VerificationRunsResponse:
    try:
        views = _service(session).list_for_incident(incident_id)
    except UnknownVerificationIncidentError as exc:
        raise api_error(status_code=404, code="INCIDENT_NOT_FOUND", message=str(exc)) from exc
    return VerificationRunsResponse(incident_id=incident_id, runs=[_response(view) for view in views])


@router.get("/verifications/{run_id}", response_model=VerificationRunResponse)
def get_verification(
    run_id: UUID,
    session: Session = Depends(get_db_session),
) -> VerificationRunResponse:
    try:
        return _response(_service(session).get_run(run_id))
    except UnknownVerificationRunError as exc:
        raise api_error(status_code=404, code="VERIFICATION_RUN_NOT_FOUND", message=str(exc)) from exc
