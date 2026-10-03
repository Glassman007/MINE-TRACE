from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.db.session import get_db_session
from app.schemas.assets import MachineComponentsResponse
from app.schemas.fleet import FleetIncidentCollectionResponse, FleetMachineCollectionResponse, FleetMachineItem, MachineSessionsResponse
from app.models import MachineRecord
from app.services.assets import AssetQueryService, UnknownMachineAssetError
from app.services.fleet_queries import FleetNotFoundError, FleetQueryService

router = APIRouter(prefix="/machines", tags=["Machines"])


@router.get("", response_model=FleetMachineCollectionResponse)
def list_machines(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    site: str | None = Query(default=None),
    machine_type: str | None = Query(default=None),
    model: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> FleetMachineCollectionResponse:
    return FleetQueryService(session).list_machines(
        offset=offset, limit=limit, search=search, site=site, machine_type=machine_type, model=model
    )


@router.get("/{machine_id}", response_model=FleetMachineItem)
def get_machine(machine_id: UUID, session: Session = Depends(get_db_session)) -> FleetMachineItem:
    try:
        return FleetQueryService(session).get_machine(machine_id)
    except FleetNotFoundError as exc:
        raise api_error(status_code=404, code="MACHINE_NOT_FOUND", message=str(exc)) from exc


@router.get("/{machine_id}/sessions", response_model=MachineSessionsResponse)
def list_machine_sessions(
    machine_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> MachineSessionsResponse:
    try:
        return FleetQueryService(session).list_sessions(machine_id, offset=offset, limit=limit)
    except FleetNotFoundError as exc:
        raise api_error(status_code=404, code="MACHINE_NOT_FOUND", message=str(exc)) from exc


@router.get("/{machine_id}/incidents", response_model=FleetIncidentCollectionResponse)
def list_machine_incidents(
    machine_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> FleetIncidentCollectionResponse:
    if session.get(MachineRecord, machine_id) is None:
        raise api_error(status_code=404, code="MACHINE_NOT_FOUND", message=f"unknown machine: {machine_id}")
    return FleetQueryService(session).list_incidents(offset=offset, limit=limit, machine_id=machine_id)


@router.get("/{machine_id}/components", response_model=MachineComponentsResponse)
def list_machine_components(
    machine_id: UUID, session: Session = Depends(get_db_session)
) -> MachineComponentsResponse:
    try:
        return AssetQueryService(uow_factory_for_session(session)).list_components(machine_id)
    except UnknownMachineAssetError as exc:
        raise api_error(status_code=404, code="MACHINE_NOT_FOUND", message=str(exc)) from exc
