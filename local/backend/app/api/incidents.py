"""Incident transport APIs. Business rules remain in services."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.db.session import get_db_session
from app.domain.enums import IncidentStatus
from app.schemas.incidents import (
    IncidentAuditResponse,
    IncidentCollectionResponse,
    IncidentDetailResponse,
    IncidentEvidenceResponse,
    MoveEvidenceRequest,
    MoveEvidenceResponse,
    SplitIncidentRequest,
    SplitIncidentResponse,
)
from app.services.incident_correction import (
    ActiveAssociationNotFoundError,
    AmbiguousActiveAssociationError,
    IncidentCorrectionService,
    InvalidCorrectionTargetError,
    UnknownCorrectionEvidenceError,
    UnknownCorrectionIncidentError,
)
from app.services.incidents import IncidentQueryService, UnknownIncidentError

router = APIRouter(prefix="/incidents", tags=["Incidents"])


def _query(session: Session) -> IncidentQueryService:
    return IncidentQueryService(uow_factory_for_session(session))


def _correction(session: Session) -> IncidentCorrectionService:
    return IncidentCorrectionService(uow_factory_for_session(session))


def _map_correction(exc: Exception):
    if isinstance(exc, (UnknownCorrectionIncidentError, UnknownCorrectionEvidenceError)):
        return api_error(status_code=404, code="CORRECTION_RESOURCE_NOT_FOUND", message=str(exc))
    return api_error(status_code=409, code="INCIDENT_CORRECTION_CONFLICT", message=str(exc))


@router.get("", response_model=IncidentCollectionResponse)
def list_incidents(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    machine_id: UUID | None = Query(default=None),
    status: IncidentStatus | None = Query(default=None),
    severity: str | None = Query(default=None),
    owner_ref: str | None = Query(default=None),
    due_state: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> IncidentCollectionResponse:
    return _query(session).list_incidents(
        offset=offset,
        limit=limit,
        machine_id=machine_id,
        status=status,
        severity=severity,
        owner_ref=owner_ref,
        due_state=due_state,
    )


@router.get("/{incident_id}", response_model=IncidentDetailResponse)
def get_incident(incident_id: UUID, session: Session = Depends(get_db_session)) -> IncidentDetailResponse:
    try:
        return _query(session).get_incident(incident_id)
    except UnknownIncidentError as exc:
        raise api_error(status_code=404, code="INCIDENT_NOT_FOUND", message=str(exc)) from exc


@router.get("/{incident_id}/audit", response_model=IncidentAuditResponse)
def get_incident_audit(incident_id: UUID, session: Session = Depends(get_db_session)) -> IncidentAuditResponse:
    try:
        return _query(session).get_incident_audit(incident_id)
    except UnknownIncidentError as exc:
        raise api_error(status_code=404, code="INCIDENT_NOT_FOUND", message=str(exc)) from exc


@router.get("/{incident_id}/evidence", response_model=IncidentEvidenceResponse)
def get_incident_evidence(incident_id: UUID, session: Session = Depends(get_db_session)) -> IncidentEvidenceResponse:
    try:
        return _query(session).get_incident_evidence(incident_id)
    except UnknownIncidentError as exc:
        raise api_error(status_code=404, code="INCIDENT_NOT_FOUND", message=str(exc)) from exc


@router.post("/{source_incident_id}/evidence/{evidence_id}/move", response_model=MoveEvidenceResponse)
def move_incident_evidence(
    source_incident_id: UUID,
    evidence_id: UUID,
    request: MoveEvidenceRequest,
    session: Session = Depends(get_db_session),
) -> MoveEvidenceResponse:
    try:
        result = _correction(session).move_evidence(
            source_incident_id=source_incident_id,
            evidence_id=evidence_id,
            target_incident_id=request.target_incident_id,
            reason=request.reason,
        )
    except (
        UnknownCorrectionIncidentError,
        UnknownCorrectionEvidenceError,
        ActiveAssociationNotFoundError,
        AmbiguousActiveAssociationError,
        InvalidCorrectionTargetError,
    ) as exc:
        raise _map_correction(exc) from exc
    return MoveEvidenceResponse(
        source_incident_id=result.source_incident_id,
        target_incident_id=result.target_incident_id,
        evidence_id=result.evidence_id,
        old_link_id=result.old_link_id,
        new_link_id=result.new_link_id,
    )


@router.post("/{source_incident_id}/split", response_model=SplitIncidentResponse)
def split_incident(
    source_incident_id: UUID,
    request: SplitIncidentRequest,
    session: Session = Depends(get_db_session),
) -> SplitIncidentResponse:
    try:
        result = _correction(session).split_incident(
            source_incident_id=source_incident_id,
            evidence_ids=request.evidence_ids,
            reason=request.reason,
        )
    except (
        UnknownCorrectionIncidentError,
        UnknownCorrectionEvidenceError,
        ActiveAssociationNotFoundError,
        AmbiguousActiveAssociationError,
        InvalidCorrectionTargetError,
    ) as exc:
        raise _map_correction(exc) from exc
    return SplitIncidentResponse(
        source_incident_id=result.source_incident_id,
        new_incident_id=result.new_incident_id,
        evidence_ids=list(result.evidence_ids),
        old_link_ids=list(result.old_link_ids),
        new_link_ids=list(result.new_link_ids),
    )
