"""Read-only controlled identity queries for machines/components."""

from collections.abc import Callable
from uuid import UUID

from app.models import ComponentRecord, MachineRecord
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.assets import (
    ComponentResponse,
    MachineCollectionResponse,
    MachineComponentsResponse,
    MachineResponse,
)


class AssetQueryError(RuntimeError):
    pass


class UnknownMachineAssetError(AssetQueryError):
    pass


class UnknownComponentAssetError(AssetQueryError):
    pass


def _machine_response(machine: MachineRecord) -> MachineResponse:
    return MachineResponse(
        id=machine.id,
        display_name=machine.display_name,
        asset_code=machine.asset_code,
        machine_type=machine.machine_type,
        manufacturer=machine.manufacturer,
        model=machine.model,
        site_name=machine.site_name,
        site_area=machine.site_area,
    )


def _component_response(component: ComponentRecord) -> ComponentResponse:
    return ComponentResponse(
        id=component.id,
        machine_id=component.machine_id,
        display_name=component.display_name,
        component_type=component.component_type,
        manufacturer=component.manufacturer,
        model=component.model,
    )


class AssetQueryService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def get_machine(self, machine_id: UUID) -> MachineResponse:
        with self._uow_factory() as uow:
            machine = uow.machines.get(machine_id)
            if machine is None:
                raise UnknownMachineAssetError(f"unknown machine: {machine_id}")
            return _machine_response(machine)

    def list_machines(
        self,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        site_name: str | None = None,
        machine_type: str | None = None,
    ) -> MachineCollectionResponse:
        with self._uow_factory() as uow:
            rows = uow.machines.list_collection(
                offset=offset,
                limit=limit,
                search=search,
                site_name=site_name,
                machine_type=machine_type,
            )
            total = uow.machines.count_collection(
                search=search,
                site_name=site_name,
                machine_type=machine_type,
            )
            return MachineCollectionResponse(
                items=[_machine_response(row) for row in rows],
                total=total,
                offset=offset,
                limit=limit,
            )

    def get_component(self, component_id: UUID) -> ComponentResponse:
        with self._uow_factory() as uow:
            component = uow.components.get(component_id)
            if component is None:
                raise UnknownComponentAssetError(f"unknown component: {component_id}")
            return _component_response(component)

    def list_components(self, machine_id: UUID) -> MachineComponentsResponse:
        with self._uow_factory() as uow:
            machine = uow.machines.get(machine_id)
            if machine is None:
                raise UnknownMachineAssetError(f"unknown machine: {machine_id}")
            return MachineComponentsResponse(
                machine_id=machine_id,
                components=[
                    _component_response(row)
                    for row in uow.components.list_for_machine(machine_id)
                ],
            )
