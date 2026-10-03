"""Transaction boundary for persistence-only repository operations."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.interfaces import (
    ComponentRepository,
    ContextSnapshotRepository,
    EvidenceAttachmentRepository,
    EvidenceEventRepository,
    HandoverItemRepository,
    HandoverPacketRepository,
    IncidentAuditEventRepository,
    IncidentEvidenceLinkRepository,
    IncidentRepository,
    MachineRepository,
    MachineSessionReportRepository,
    OperatingSessionRepository,
    SyncConflictRepository,
    SyncOutboxRepository,
    VerificationEvidenceRepository,
    VerificationRuleRepository,
    VerificationRunRepository,
)
from app.repositories.sqlalchemy import (
    SQLAlchemyComponentRepository,
    SQLAlchemyContextSnapshotRepository,
    SQLAlchemyEvidenceAttachmentRepository,
    SQLAlchemyEvidenceEventRepository,
    SQLAlchemyHandoverItemRepository,
    SQLAlchemyHandoverPacketRepository,
    SQLAlchemyIncidentAuditEventRepository,
    SQLAlchemyIncidentEvidenceLinkRepository,
    SQLAlchemyIncidentRepository,
    SQLAlchemyMachineRepository,
    SQLAlchemyMachineSessionReportRepository,
    SQLAlchemyOperatingSessionRepository,
    SQLAlchemySyncConflictRepository,
    SQLAlchemySyncOutboxRepository,
    SQLAlchemyVerificationEvidenceRepository,
    SQLAlchemyVerificationRuleRepository,
    SQLAlchemyVerificationRunRepository,
)


class UnitOfWork(Protocol):
    machines: MachineRepository
    components: ComponentRepository
    evidence_events: EvidenceEventRepository
    evidence_attachments: EvidenceAttachmentRepository
    context_snapshots: ContextSnapshotRepository
    incidents: IncidentRepository
    incident_evidence_links: IncidentEvidenceLinkRepository
    incident_audit_events: IncidentAuditEventRepository
    verification_rules: VerificationRuleRepository
    verification_runs: VerificationRunRepository
    verification_evidence: VerificationEvidenceRepository
    operating_sessions: OperatingSessionRepository
    machine_session_reports: MachineSessionReportRepository
    sync_outbox: SyncOutboxRepository
    sync_conflicts: SyncConflictRepository
    handover_packets: HandoverPacketRepository
    handover_items: HandoverItemRepository

    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    def flush(self) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class SQLAlchemyUnitOfWork:
    """Owns one SQLAlchemy Session and all repositories for one transaction.

    Persistence is explicit: callers must invoke ``commit()``. An exception, or
    leaving the context with uncommitted work, rolls the transaction back.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        close_session: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._close_session = close_session
        self._session: Session | None = None

    def __enter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("UnitOfWork is already active")

        session = self._session_factory()
        self._session = session

        self.machines = SQLAlchemyMachineRepository(session)
        self.components = SQLAlchemyComponentRepository(session)
        self.evidence_events = SQLAlchemyEvidenceEventRepository(session)
        self.evidence_attachments = SQLAlchemyEvidenceAttachmentRepository(session)
        self.context_snapshots = SQLAlchemyContextSnapshotRepository(session)
        self.incidents = SQLAlchemyIncidentRepository(session)
        self.incident_evidence_links = SQLAlchemyIncidentEvidenceLinkRepository(session)
        self.incident_audit_events = SQLAlchemyIncidentAuditEventRepository(session)
        self.verification_rules = SQLAlchemyVerificationRuleRepository(session)
        self.verification_runs = SQLAlchemyVerificationRunRepository(session)
        self.verification_evidence = SQLAlchemyVerificationEvidenceRepository(session)
        self.operating_sessions = SQLAlchemyOperatingSessionRepository(session)
        self.machine_session_reports = SQLAlchemyMachineSessionReportRepository(session)
        self.sync_outbox = SQLAlchemySyncOutboxRepository(session)
        self.sync_conflicts = SQLAlchemySyncConflictRepository(session)
        self.handover_packets = SQLAlchemyHandoverPacketRepository(session)
        self.handover_items = SQLAlchemyHandoverItemRepository(session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc_type is not None or session.in_transaction():
                session.rollback()
        finally:
            if self._close_session:
                session.close()
            self._session = None

    def flush(self) -> None:
        self._require_session().flush()

    def commit(self) -> None:
        self._require_session().commit()

    def rollback(self) -> None:
        self._require_session().rollback()

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be used inside a context manager")
        return self._session
