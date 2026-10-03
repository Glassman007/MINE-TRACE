from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.core.settings import Settings
from app.core.time import normalize_to_utc, restore_utc
from app.domain.enums import OperatingSessionState
from app.models import OperatingSessionRecord
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.session_reports import MachineSessionReportResponse
from app.schemas.sessions import OperatingSessionResponse
from app.services.session_reports import MachineSessionReportService
from app.services.sync import SyncOutboxService


class OperatingSessionError(RuntimeError):
    pass


class LocalMachineNotConfiguredError(OperatingSessionError):
    pass


class ConfiguredMachineNotFoundError(OperatingSessionError):
    pass


class OperatingSessionNotFoundError(OperatingSessionError):
    pass


class ActiveOperatingSessionExistsError(OperatingSessionError):
    pass


class NoActiveOperatingSessionError(OperatingSessionError):
    pass


class OperatingSessionStateError(OperatingSessionError):
    pass


class OperatingSessionTimeError(OperatingSessionError):
    pass


@dataclass(frozen=True, slots=True)
class ClosedSessionResult:
    session: OperatingSessionResponse
    report: MachineSessionReportResponse


@dataclass(frozen=True, slots=True)
class SessionRolloverResult:
    closed_session: OperatingSessionResponse
    report: MachineSessionReportResponse
    new_session: OperatingSessionResponse


class OperatingSessionService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        settings: Settings,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._reports = MachineSessionReportService(settings)
        self._sync = SyncOutboxService(
            uow_factory, settings, clock=self._clock
        )

    def open_session(self, *, started_at: datetime) -> OperatingSessionResponse:
        machine_id = self._configured_machine_id()
        started_at = normalize_to_utc(started_at)
        now = normalize_to_utc(self._clock())
        try:
            with self._uow_factory() as uow:
                self._require_machine(uow, machine_id)
                if uow.operating_sessions.get_active_for_machine(machine_id) is not None:
                    raise ActiveOperatingSessionExistsError(
                        f"active operating session already exists for machine: {machine_id}"
                    )
                record = OperatingSessionRecord(
                    session_id=uuid4(),
                    machine_id=machine_id,
                    started_at=started_at,
                    ended_at=None,
                    state=OperatingSessionState.OPEN,
                    operating_hours=None,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
                uow.operating_sessions.add(record)
                uow.flush()
                view = self._view(record)
                uow.commit()
                return view
        except IntegrityError as exc:
            raise ActiveOperatingSessionExistsError(
                f"active operating session already exists for machine: {machine_id}"
            ) from exc

    def get_session(self, session_id: UUID) -> OperatingSessionResponse:
        machine_id = self._configured_machine_id()
        with self._uow_factory() as uow:
            record = uow.operating_sessions.get(session_id)
            if record is None or record.machine_id != machine_id:
                raise OperatingSessionNotFoundError(f"operating session not found: {session_id}")
            return self._view(record)

    def get_active_session(self) -> OperatingSessionResponse:
        machine_id = self._configured_machine_id()
        with self._uow_factory() as uow:
            record = uow.operating_sessions.get_active_for_machine(machine_id)
            if record is None:
                raise NoActiveOperatingSessionError(
                    f"no active operating session for machine: {machine_id}"
                )
            return self._view(record)

    def close_session(
        self,
        session_id: UUID,
        *,
        ended_at: datetime,
        operating_hours: float | None,
    ) -> ClosedSessionResult:
        machine_id = self._configured_machine_id()
        with self._uow_factory() as uow:
            record = uow.operating_sessions.get(session_id)
            if record is None or record.machine_id != machine_id:
                raise OperatingSessionNotFoundError(f"operating session not found: {session_id}")
            self._close_record(
                record,
                ended_at=ended_at,
                operating_hours=operating_hours,
            )
            uow.flush()
            report = self._reports.generate_in_uow(uow, record)
            self._sync.queue_report_in_uow(uow, report)
            view = self._view(record)
            uow.commit()
            return ClosedSessionResult(session=view, report=report)

    def rollover(
        self,
        *,
        ended_at: datetime,
        new_started_at: datetime,
        operating_hours: float | None,
    ) -> SessionRolloverResult:
        machine_id = self._configured_machine_id()
        ended_at = normalize_to_utc(ended_at)
        new_started_at = normalize_to_utc(new_started_at)
        if new_started_at < ended_at:
            raise OperatingSessionTimeError(
                "new session start must not be before the closing session end"
            )
        now = normalize_to_utc(self._clock())
        with self._uow_factory() as uow:
            self._require_machine(uow, machine_id)
            active = uow.operating_sessions.get_active_for_machine(machine_id)
            if active is None:
                raise NoActiveOperatingSessionError(
                    f"no active operating session for machine: {machine_id}"
                )
            self._close_record(
                active,
                ended_at=ended_at,
                operating_hours=operating_hours,
            )
            uow.flush()
            report = self._reports.generate_in_uow(uow, active)
            self._sync.queue_report_in_uow(uow, report)
            closed_view = self._view(active)

            new_record = OperatingSessionRecord(
                session_id=uuid4(),
                machine_id=machine_id,
                started_at=new_started_at,
                ended_at=None,
                state=OperatingSessionState.OPEN,
                operating_hours=None,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            uow.operating_sessions.add(new_record)
            uow.flush()
            new_view = self._view(new_record)
            uow.commit()
            return SessionRolloverResult(
                closed_session=closed_view,
                report=report,
                new_session=new_view,
            )

    def get_report(self, session_id: UUID) -> MachineSessionReportResponse:
        machine_id = self._configured_machine_id()
        with self._uow_factory() as uow:
            session_record = uow.operating_sessions.get(session_id)
            if session_record is None or session_record.machine_id != machine_id:
                raise OperatingSessionNotFoundError(f"operating session not found: {session_id}")
            return self._reports.get_in_uow(uow, session_id)

    def _close_record(
        self,
        record: OperatingSessionRecord,
        *,
        ended_at: datetime,
        operating_hours: float | None,
    ) -> None:
        if record.state != OperatingSessionState.OPEN:
            raise OperatingSessionStateError(
                f"operating session is not open: {record.session_id}"
            )
        ended_at = normalize_to_utc(ended_at)
        started_at = normalize_to_utc(record.started_at)
        if ended_at < started_at:
            raise OperatingSessionTimeError("session end must not be before session start")
        if operating_hours is not None and operating_hours < 0:
            raise OperatingSessionError("operating_hours must be non-negative")
        record.ended_at = ended_at
        record.operating_hours = operating_hours
        record.state = OperatingSessionState.CLOSED
        record.revision += 1
        record.updated_at = normalize_to_utc(self._clock())

    def _configured_machine_id(self) -> UUID:
        if self._settings.local_machine_id is None:
            raise LocalMachineNotConfiguredError("local_machine_id is not configured")
        return self._settings.local_machine_id

    @staticmethod
    def _require_machine(uow: UnitOfWork, machine_id: UUID) -> None:
        if uow.machines.get(machine_id) is None:
            raise ConfiguredMachineNotFoundError(
                f"configured local machine does not exist: {machine_id}"
            )

    @staticmethod
    def _view(record: OperatingSessionRecord) -> OperatingSessionResponse:
        return OperatingSessionResponse(
            session_id=record.session_id,
            machine_id=record.machine_id,
            started_at=restore_utc(record.started_at),
            ended_at=restore_utc(record.ended_at),
            state=record.state,
            operating_hours=record.operating_hours,
            revision=record.revision,
            created_at=restore_utc(record.created_at),
            updated_at=restore_utc(record.updated_at),
        )
