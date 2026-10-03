"""Incident transport APIs. Business rules remain in services."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.db.session import get_db_session
from app.domain.enums import IncidentStatus
from app.schemas.fleet import FleetIncidentCollectionResponse
from app.schemas.incidents import (
    IncidentAuditResponse,
    IncidentCollectionResponse,
    IncidentDetailResponse,
    IncidentEvidenceResponse,
    IncidentMaintenanceActionItem,
    IncidentMaintenanceActionsResponse,
)
from app.models import IncidentRecord, MaintenanceActionRecord
from app.services.incidents import IncidentQueryService, UnknownIncidentError

router = APIRouter(prefix="/incidents", tags=["Incidents"])


def _query(session: Session) -> IncidentQueryService:
    return IncidentQueryService(uow_factory_for_session(session))



@router.get("", response_model=FleetIncidentCollectionResponse)
def list_incidents(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    machine_id: UUID | None = Query(default=None, alias="machine"),
    component_id: UUID | None = Query(default=None, alias="component"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    status: IncidentStatus | None = Query(default=None),
    state: IncidentStatus | None = Query(default=None),
    model: str | None = Query(default=None),
    site: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
):
    from app.services.fleet_queries import FleetQueryService
    if status is not None and state is not None and status is not state:
        raise api_error(status_code=422, code="INCIDENT_FILTER_CONFLICT", message="status and state filters must match when both are supplied")
    effective_status = status or state
    return FleetQueryService(session).list_incidents(
        offset=offset, limit=limit, machine_id=machine_id, component_id=component_id,
        start=start, end=end, status=effective_status, model=model, site=site,
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



@router.get("/{incident_id}/maintenance-actions", response_model=IncidentMaintenanceActionsResponse)
def get_incident_maintenance_actions(incident_id: UUID, session: Session = Depends(get_db_session)) -> IncidentMaintenanceActionsResponse:
    if session.get(IncidentRecord, incident_id) is None:
        raise api_error(status_code=404, code="INCIDENT_NOT_FOUND", message=f"unknown incident: {incident_id}")
    rows = session.scalars(
        select(MaintenanceActionRecord)
        .where(MaintenanceActionRecord.incident_id == incident_id)
        .order_by(MaintenanceActionRecord.original_timestamp.desc(), MaintenanceActionRecord.id.desc())
    ).all()
    return IncidentMaintenanceActionsResponse(
        incident_id=incident_id,
        actions=[
            IncidentMaintenanceActionItem(
                action_id=row.id,
                machine_id=row.machine_id,
                incident_id=row.incident_id,
                session_id=row.session_id,
                component_id=row.component_id,
                action_type=row.action_type,
                description=row.description,
                original_timestamp=row.original_timestamp,
                ingestion_timestamp=row.ingestion_timestamp,
                source_report_revision=row.source_report_revision,
                provenance=row.provenance,
            )
            for row in rows
        ],
    )
