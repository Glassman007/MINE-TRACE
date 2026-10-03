"""Configured-machine local overview assembled from canonical SQLite state."""

from collections.abc import Callable

from app.core.settings import Settings
from app.core.time import restore_utc
from app.domain.enums import IncidentStatus
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.assets import MachineResponse
from app.schemas.overview import (
    LocalOverviewCounts,
    LocalReturnToServiceSummary,
    LocalSyncTransportSummary,
    OverviewResponse,
)
from app.schemas.sessions import OperatingSessionResponse
from app.services.return_to_service import ReturnToServiceService
from app.services.sync import SyncStatusService


class OverviewConfigurationError(RuntimeError):
    pass


class ConfiguredOverviewMachineNotFoundError(RuntimeError):
    pass


_UNRESOLVED_STATUSES = (
    IncidentStatus.OPEN,
    IncidentStatus.VERIFYING,
    IncidentStatus.RECURRED,
)


class OverviewQueryService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings

    def get_overview(self) -> OverviewResponse:
        machine_id = self._settings.local_machine_id
        if machine_id is None:
            raise OverviewConfigurationError("local_machine_id is not configured")

        # These services are intentionally deterministic and SQLite-only. They
        # are evaluated separately so no nested UoW can roll back another read.
        return_to_service = ReturnToServiceService(
            self._settings, self._uow_factory
        ).evaluate()
        sync = SyncStatusService(self._uow_factory, self._settings).get_status()

        with self._uow_factory() as uow:
            machine = uow.machines.get(machine_id)
            if machine is None:
                raise ConfiguredOverviewMachineNotFoundError(
                    f"configured local machine not found: {machine_id}"
                )

            active = uow.operating_sessions.get_active_for_machine(machine_id)
            counts_by_status = {
                status.value: uow.incidents.count_collection(
                    machine_id=machine_id, status=status
                )
                for status in IncidentStatus
            }
            unresolved = sum(counts_by_status[status.value] for status in _UNRESOLVED_STATUSES)

            active_session = None
            if active is not None:
                active_session = OperatingSessionResponse(
                    session_id=active.session_id,
                    machine_id=active.machine_id,
                    started_at=restore_utc(active.started_at),
                    ended_at=restore_utc(active.ended_at) if active.ended_at else None,
                    state=active.state,
                    operating_hours=active.operating_hours,
                    revision=active.revision,
                    created_at=restore_utc(active.created_at),
                    updated_at=restore_utc(active.updated_at),
                )

            return OverviewResponse(
                demo_mode=self._settings.demo_mode,
                machine=MachineResponse(
                    id=machine.id,
                    display_name=machine.display_name,
                    asset_code=machine.asset_code,
                    machine_type=machine.machine_type,
                    manufacturer=machine.manufacturer,
                    model=machine.model,
                    site_name=machine.site_name,
                    site_area=machine.site_area,
                ),
                active_session=active_session,
                operating_state=active.state if active is not None else None,
                unresolved_incident_count=unresolved,
                counts=LocalOverviewCounts(
                    components=uow.components.count_for_machine(machine_id),
                    evidence=uow.evidence_events.count_for_machine(machine_id),
                    incidents=sum(counts_by_status.values()),
                    incidents_by_status=counts_by_status,
                ),
                return_to_service=LocalReturnToServiceSummary(
                    state=return_to_service.state,
                    blocking_reasons=return_to_service.blocking_reasons,
                    policy_identifier=return_to_service.policy_identifier,
                    policy_revision=return_to_service.policy_revision,
                ),
                sync=LocalSyncTransportSummary(
                    transport_configured=sync.transport_configured,
                    transport_available=sync.transport_available,
                    transport_checked_at=sync.transport_checked_at,
                    latest_package_state=(
                        sync.latest_package.state if sync.latest_package is not None else None
                    ),
                    last_acknowledgement=sync.last_acknowledgement,
                    last_error=sync.last_error,
                ),
            )
