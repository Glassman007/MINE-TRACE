"""Persistence-only repository contracts for the MINE-TRACE MVP.

These interfaces deliberately expose storage primitives, not domain decisions.
Transaction ownership belongs to the Unit of Work and business rules belong to
services/domain code.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.enums import IncidentStatus, OperatingSessionState, SyncOutboxState
from app.models import (
    ComponentRecord,
    ContextSnapshotRecord,
    EvidenceAttachmentRecord,
    EvidenceEventRecord,
    HandoverItemRecord,
    HandoverPacketRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
    MachineSessionReportRecord,
    OperatingSessionRecord,
    SyncConflictRecord,
    SyncOutboxItemRecord,
    VerificationEvidenceRecord,
    VerificationRuleRecord,
    VerificationRunRecord,
)


class MachineRepository(Protocol):
    def add(self, record: MachineRecord) -> None: ...
    def get(self, record_id: UUID) -> MachineRecord | None: ...
    def list_collection(
        self,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        site_name: str | None = None,
        machine_type: str | None = None,
    ) -> Sequence[MachineRecord]: ...
    def count_collection(
        self,
        *,
        search: str | None = None,
        site_name: str | None = None,
        machine_type: str | None = None,
    ) -> int: ...


class ComponentRepository(Protocol):
    def add(self, record: ComponentRecord) -> None: ...
    def get(self, record_id: UUID) -> ComponentRecord | None: ...
    def list_for_machine(self, machine_id: UUID) -> Sequence[ComponentRecord]: ...
    def count_all(self) -> int: ...
    def count_for_machine(self, machine_id: UUID) -> int: ...


class EvidenceEventRepository(Protocol):
    def add(self, record: EvidenceEventRecord) -> None: ...
    def get(self, record_id: UUID) -> EvidenceEventRecord | None: ...
    def get_by_source_identity(
        self, source_type: str, original_source_record_id: str
    ) -> EvidenceEventRecord | None: ...
    def list_machine_timeline(
        self,
        machine_id: UUID,
        *,
        component_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Sequence[EvidenceEventRecord]: ...
    def list_component_timeline(
        self,
        component_id: UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Sequence[EvidenceEventRecord]: ...
    def list_for_semantic_indexing(
        self,
        *,
        offset: int,
        limit: int,
    ) -> Sequence[EvidenceEventRecord]: ...
    def list_for_session(self, session_id: UUID) -> Sequence[EvidenceEventRecord]: ...
    def count_for_machine(self, machine_id: UUID) -> int: ...


class EvidenceAttachmentRepository(Protocol):
    def add(self, record: EvidenceAttachmentRecord) -> None: ...
    def get(self, record_id: UUID) -> EvidenceAttachmentRecord | None: ...
    def list_for_evidence(
        self, evidence_event_id: UUID
    ) -> Sequence[EvidenceAttachmentRecord]: ...


class ContextSnapshotRepository(Protocol):
    def add(self, record: ContextSnapshotRecord) -> None: ...
    def get(self, record_id: UUID) -> ContextSnapshotRecord | None: ...
    def list_for_evidence(
        self, evidence_event_id: UUID
    ) -> Sequence[ContextSnapshotRecord]: ...


class IncidentRepository(Protocol):
    def add(self, record: IncidentRecord) -> None: ...
    def get(self, record_id: UUID) -> IncidentRecord | None: ...
    def list_for_machine(
        self, machine_id: UUID, *, status: IncidentStatus | None = None
    ) -> Sequence[IncidentRecord]: ...
    def list_by_statuses(
        self, statuses: Sequence[IncidentStatus]
    ) -> Sequence[IncidentRecord]: ...
    def list_collection(
        self,
        *,
        offset: int,
        limit: int,
        machine_id: UUID | None = None,
        status: IncidentStatus | None = None,
        severity: str | None = None,
        owner_ref: str | None = None,
        due_state: str | None = None,
    ) -> Sequence[IncidentRecord]: ...
    def count_collection(
        self,
        *,
        machine_id: UUID | None = None,
        status: IncidentStatus | None = None,
        severity: str | None = None,
        owner_ref: str | None = None,
        due_state: str | None = None,
    ) -> int: ...
    def count_by_status(self) -> dict[IncidentStatus, int]: ...


class IncidentEvidenceLinkRepository(Protocol):
    def add(self, record: IncidentEvidenceLinkRecord) -> None: ...
    def get(self, record_id: UUID) -> IncidentEvidenceLinkRecord | None: ...
    def list_for_incident(
        self, incident_id: UUID
    ) -> Sequence[IncidentEvidenceLinkRecord]: ...
    def list_active_for_incident(
        self, incident_id: UUID
    ) -> Sequence[IncidentEvidenceLinkRecord]: ...
    def list_active_for_evidence(
        self, evidence_event_id: UUID
    ) -> Sequence[IncidentEvidenceLinkRecord]: ...
    def deactivate(
        self, record_id: UUID, *, unlinked_at: datetime
    ) -> IncidentEvidenceLinkRecord | None: ...


class IncidentAuditEventRepository(Protocol):
    """Append-only repository contract: intentionally no update/delete methods."""

    def add(self, record: IncidentAuditEventRecord) -> None: ...
    def get(self, record_id: UUID) -> IncidentAuditEventRecord | None: ...
    def list_for_incident(
        self, incident_id: UUID
    ) -> Sequence[IncidentAuditEventRecord]: ...


class VerificationRuleRepository(Protocol):
    def add(self, record: VerificationRuleRecord) -> None: ...
    def get(self, record_id: UUID) -> VerificationRuleRecord | None: ...
    def get_by_identifier(self, identifier: str) -> VerificationRuleRecord | None: ...


class VerificationRunRepository(Protocol):
    def add(self, record: VerificationRunRecord) -> None: ...
    def get(self, record_id: UUID) -> VerificationRunRecord | None: ...
    def list_for_incident(
        self, incident_id: UUID
    ) -> Sequence[VerificationRunRecord]: ...
    def list_for_rule(
        self, verification_rule_id: UUID
    ) -> Sequence[VerificationRunRecord]: ...
    def list_pending_for_incident(
        self, incident_id: UUID
    ) -> Sequence[VerificationRunRecord]: ...
    def list_due(self, as_of: datetime) -> Sequence[VerificationRunRecord]: ...


class VerificationEvidenceRepository(Protocol):
    def add(self, record: VerificationEvidenceRecord) -> None: ...
    def get(self, record_id: UUID) -> VerificationEvidenceRecord | None: ...
    def list_for_run(
        self, verification_run_id: UUID
    ) -> Sequence[VerificationEvidenceRecord]: ...


class OperatingSessionRepository(Protocol):
    def add(self, record: OperatingSessionRecord) -> None: ...
    def get(self, record_id: UUID) -> OperatingSessionRecord | None: ...
    def get_active_for_machine(self, machine_id: UUID) -> OperatingSessionRecord | None: ...
    def list_for_machine(
        self, machine_id: UUID, *, state: OperatingSessionState | None = None
    ) -> Sequence[OperatingSessionRecord]: ...


class MachineSessionReportRepository(Protocol):
    def add(self, record: MachineSessionReportRecord) -> None: ...
    def get(self, record_id: UUID) -> MachineSessionReportRecord | None: ...
    def get_for_session(
        self, session_id: UUID, *, report_revision: int = 1
    ) -> MachineSessionReportRecord | None: ...


class SyncOutboxRepository(Protocol):
    def add(self, record: SyncOutboxItemRecord) -> None: ...
    def get(self, record_id: UUID) -> SyncOutboxItemRecord | None: ...
    def get_by_package_revision(
        self, package_id: UUID, local_revision: int
    ) -> SyncOutboxItemRecord | None: ...
    def list_for_machine(
        self, machine_id: UUID, *, states: Sequence[SyncOutboxState] | None = None
    ) -> Sequence[SyncOutboxItemRecord]: ...
    def count_for_machine_by_state(
        self, machine_id: UUID
    ) -> dict[SyncOutboxState, int]: ...
    def get_most_recent_for_machine(
        self, machine_id: UUID
    ) -> SyncOutboxItemRecord | None: ...


class SyncConflictRepository(Protocol):
    def add(self, record: SyncConflictRecord) -> None: ...
    def get(self, record_id: UUID) -> SyncConflictRecord | None: ...
    def get_for_revisions(
        self, package_id: UUID, local_revision: int, central_revision: int
    ) -> SyncConflictRecord | None: ...
    def list_for_machine(self, machine_id: UUID) -> Sequence[SyncConflictRecord]: ...
    def count_for_machine(self, machine_id: UUID) -> int: ...


class HandoverPacketRepository(Protocol):
    def add(self, record: HandoverPacketRecord) -> None: ...
    def get(self, record_id: UUID) -> HandoverPacketRecord | None: ...


class HandoverItemRepository(Protocol):
    def add(self, record: HandoverItemRecord) -> None: ...
    def get(self, record_id: UUID) -> HandoverItemRecord | None: ...
    def list_for_packet(
        self, handover_packet_id: UUID
    ) -> Sequence[HandoverItemRecord]: ...
    def list_for_incident(self, incident_id: UUID) -> Sequence[HandoverItemRecord]: ...
