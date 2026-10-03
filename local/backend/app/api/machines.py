from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.assets import MachineCollectionResponse, MachineComponentsResponse, MachineResponse
from app.services.assets import AssetQueryService, UnknownMachineAssetError

router = APIRouter(prefix="/machines", tags=["Machines"])


def _configured_machine_id(settings: Settings) -> UUID:
    if settings.local_machine_id is None:
        raise api_error(
            status_code=503,
            code="LOCAL_MACHINE_NOT_CONFIGURED",
            message="local_machine_id is not configured",
        )
    return settings.local_machine_id


@router.get("/current", response_model=MachineResponse)
def get_current_machine(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> MachineResponse:
    machine_id = _configured_machine_id(settings)
    try:
        return AssetQueryService(uow_factory_for_session(session)).get_machine(machine_id)
    except UnknownMachineAssetError as exc:
        raise api_error(
            status_code=404,
            code="CONFIGURED_MACHINE_NOT_FOUND",
            message=str(exc),
        ) from exc


@router.get("/current/components", response_model=MachineComponentsResponse)
def list_current_machine_components(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> MachineComponentsResponse:
    machine_id = _configured_machine_id(settings)
    try:
        return AssetQueryService(uow_factory_for_session(session)).list_components(machine_id)
    except UnknownMachineAssetError as exc:
        raise api_error(
            status_code=404,
            code="CONFIGURED_MACHINE_NOT_FOUND",
            message=str(exc),
        ) from exc


@router.get(
    "",
    response_model=MachineCollectionResponse,
    deprecated=True,
    description=(
        "Compatibility collection endpoint. The local-node UI must use "
        "/machines/current and must not treat this edge API as a fleet browser."
    ),
)
def list_machines(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    site_name: str | None = Query(default=None),
    machine_type: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> MachineCollectionResponse:
    return AssetQueryService(uow_factory_for_session(session)).list_machines(
        offset=offset,
        limit=limit,
        search=search,
        site_name=site_name,
        machine_type=machine_type,
    )


@router.get("/{machine_id}", response_model=MachineResponse)
def get_machine(machine_id: UUID, session: Session = Depends(get_db_session)) -> MachineResponse:
    try:
        return AssetQueryService(uow_factory_for_session(session)).get_machine(machine_id)
    except UnknownMachineAssetError as exc:
        raise api_error(status_code=404, code="MACHINE_NOT_FOUND", message=str(exc)) from exc


@router.get("/{machine_id}/components", response_model=MachineComponentsResponse)
def list_machine_components(
    machine_id: UUID, session: Session = Depends(get_db_session)
) -> MachineComponentsResponse:
    try:
        return AssetQueryService(uow_factory_for_session(session)).list_components(machine_id)
    except UnknownMachineAssetError as exc:
        raise api_error(status_code=404, code="MACHINE_NOT_FOUND", message=str(exc)) from exc
