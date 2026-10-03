"""Authoritative PostgreSQL-derived global dashboard summary."""

from collections.abc import Callable

from app.domain.enums import IncidentStatus
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.overview import OverviewResponse


class OverviewQueryService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def get_overview(self) -> OverviewResponse:
        with self._uow_factory() as uow:
            counts = uow.incidents.count_by_status()
            by_status = {
                status.value: counts.get(status, 0)
                for status in IncidentStatus
            }
            return OverviewResponse(
                machines_total=uow.machines.count_collection(),
                components_total=uow.components.count_all(),
                incidents_total=uow.incidents.count_collection(),
                incidents_by_status=by_status,
            )
