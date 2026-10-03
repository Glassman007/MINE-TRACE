"""SQLAlchemy implementations of the MINE-TRACE persistence repositories."""

from collections.abc import Sequence
from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.domain.enums import IncidentStatus
from app.models import (
    ComponentRecord,
    ContextSnapshotRecord,
    EvidenceAttachmentRecord,
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
    VerificationEvidenceRecord,
    VerificationRuleRecord,
    VerificationRunRecord,
)

RecordT = TypeVar("RecordT")


class _RepositoryBase(Generic[RecordT]):
    """Small internal helper for shared add/get persistence plumbing only."""

    record_type: type[RecordT]

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: RecordT) -> None:
        self._session.add(record)

    def get(self, record_id: UUID) -> RecordT | None:
        return self._session.get(self.record_type, record_id)


class SQLAlchemyMachineRepository(_RepositoryBase[MachineRecord]):
    record_type = MachineRecord

    @staticmethod
    def _apply_collection_filters(statement, *, search, site_name, machine_type):
        if search is not None and (needle := search.strip().lower()):
            searchable = (
                MachineRecord.display_name,
                MachineRecord.asset_code,
                MachineRecord.machine_type,
                MachineRecord.manufacturer,
                MachineRecord.model,
                MachineRecord.site_name,
                MachineRecord.site_area,
            )
            statement = statement.where(
                or_(
                    *(
                        func.lower(column).contains(needle, autoescape=True)
                        for column in searchable
                    )
                )
            )
        if site_name is not None:
            statement = statement.where(MachineRecord.site_name == site_name)
        if machine_type is not None:
            statement = statement.where(MachineRecord.machine_type == machine_type)
        return statement

    def list_collection(
        self,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        site_name: str | None = None,
        machine_type: str | None = None,
    ) -> Sequence[MachineRecord]:
        statement = self._apply_collection_filters(
            select(MachineRecord),
            search=search,
            site_name=site_name,
            machine_type=machine_type,
        ).order_by(
            case((MachineRecord.display_name.is_(None), 1), else_=0),
            MachineRecord.display_name.asc(),
            MachineRecord.id.asc(),
        ).offset(offset).limit(limit)
        return self._session.scalars(statement).all()

    def count_collection(
        self,
        *,
        search: str | None = None,
        site_name: str | None = None,
        machine_type: str | None = None,
    ) -> int:
        statement = self._apply_collection_filters(
            select(func.count()).select_from(MachineRecord),
            search=search,
            site_name=site_name,
            machine_type=machine_type,
        )
        return int(self._session.scalar(statement) or 0)


class SQLAlchemyComponentRepository(_RepositoryBase[ComponentRecord]):
    record_type = ComponentRecord

    def list_for_machine(self, machine_id: UUID) -> Sequence[ComponentRecord]:
        statement = (
            select(ComponentRecord)
            .where(ComponentRecord.machine_id == machine_id)
            .order_by(ComponentRecord.id)
        )
        return self._session.scalars(statement).all()

    def count_all(self) -> int:
        statement = select(func.count()).select_from(ComponentRecord)
        return int(self._session.scalar(statement) or 0)


class SQLAlchemyEvidenceEventRepository(_RepositoryBase[EvidenceEventRecord]):
    record_type = EvidenceEventRecord

    def get_by_source_identity(
        self, source_type: str, original_source_record_id: str
    ) -> EvidenceEventRecord | None:
        statement = select(EvidenceEventRecord).where(
            EvidenceEventRecord.source_type == source_type,
            EvidenceEventRecord.original_source_record_id == original_source_record_id,
        )
        return self._session.scalar(statement)

    def list_machine_timeline(
        self,
        machine_id: UUID,
        *,
        component_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Sequence[EvidenceEventRecord]:
        statement = select(EvidenceEventRecord).where(
            EvidenceEventRecord.machine_id == machine_id
        )
        if component_id is not None:
            statement = statement.where(EvidenceEventRecord.component_id == component_id)
        if start is not None:
            statement = statement.where(EvidenceEventRecord.original_timestamp >= start)
        if end is not None:
            statement = statement.where(EvidenceEventRecord.original_timestamp <= end)
        # Historical order is defined only by the source's original timestamp.
        # ID is a deterministic tie-breaker for equal original timestamps.
        statement = statement.order_by(
            EvidenceEventRecord.original_timestamp, EvidenceEventRecord.id
        )
        return self._session.scalars(statement).all()

    def list_component_timeline(
        self,
        component_id: UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Sequence[EvidenceEventRecord]:
        statement = select(EvidenceEventRecord).where(
            EvidenceEventRecord.component_id == component_id
        )
        if start is not None:
            statement = statement.where(EvidenceEventRecord.original_timestamp >= start)
        if end is not None:
            statement = statement.where(EvidenceEventRecord.original_timestamp <= end)
        statement = statement.order_by(
            EvidenceEventRecord.original_timestamp, EvidenceEventRecord.id
        )
        return self._session.scalars(statement).all()

    def list_for_semantic_indexing(
        self,
        *,
        offset: int,
        limit: int,
    ) -> Sequence[EvidenceEventRecord]:
        """Enumerate canonical evidence deterministically for derived indexing."""

        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = (
            select(EvidenceEventRecord)
            .order_by(EvidenceEventRecord.id)
            .offset(offset)
            .limit(limit)
        )
        return self._session.scalars(statement).all()


class SQLAlchemyEvidenceAttachmentRepository(_RepositoryBase[EvidenceAttachmentRecord]):
    record_type = EvidenceAttachmentRecord

    def list_for_evidence(
        self, evidence_event_id: UUID
    ) -> Sequence[EvidenceAttachmentRecord]:
        statement = (
            select(EvidenceAttachmentRecord)
            .where(EvidenceAttachmentRecord.evidence_event_id == evidence_event_id)
            .order_by(EvidenceAttachmentRecord.id)
        )
        return self._session.scalars(statement).all()


class SQLAlchemyContextSnapshotRepository(_RepositoryBase[ContextSnapshotRecord]):
    record_type = ContextSnapshotRecord

    def list_for_evidence(
        self, evidence_event_id: UUID
    ) -> Sequence[ContextSnapshotRecord]:
        statement = (
            select(ContextSnapshotRecord)
            .where(ContextSnapshotRecord.evidence_event_id == evidence_event_id)
            .order_by(ContextSnapshotRecord.id)
        )
        return self._session.scalars(statement).all()


class SQLAlchemyIncidentRepository(_RepositoryBase[IncidentRecord]):
    record_type = IncidentRecord

    def list_for_machine(
        self, machine_id: UUID, *, status: IncidentStatus | None = None
    ) -> Sequence[IncidentRecord]:
        statement = select(IncidentRecord).where(IncidentRecord.machine_id == machine_id)
        if status is not None:
            statement = statement.where(IncidentRecord.status == status)
        statement = statement.order_by(IncidentRecord.created_at, IncidentRecord.id)
        return self._session.scalars(statement).all()

    def list_by_statuses(
        self, statuses: Sequence[IncidentStatus]
    ) -> Sequence[IncidentRecord]:
        if not statuses:
            return []
        statement = (
            select(IncidentRecord)
            .where(IncidentRecord.status.in_(tuple(statuses)))
            .order_by(IncidentRecord.created_at, IncidentRecord.id)
        )
        return self._session.scalars(statement).all()

    @staticmethod
    def _apply_collection_filters(
        statement,
        *,
        machine_id,
        status,
        severity,
        owner_ref,
        due_state,
    ):
        if machine_id is not None:
            statement = statement.where(IncidentRecord.machine_id == machine_id)
        if status is not None:
            statement = statement.where(IncidentRecord.status == status)
        if severity is not None:
            statement = statement.where(IncidentRecord.severity == severity)
        if owner_ref is not None:
            statement = statement.where(IncidentRecord.owner_ref == owner_ref)
        if due_state is not None:
            statement = statement.where(IncidentRecord.due_state == due_state)
        return statement

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
    ) -> Sequence[IncidentRecord]:
        statement = self._apply_collection_filters(
            select(IncidentRecord),
            machine_id=machine_id,
            status=status,
            severity=severity,
            owner_ref=owner_ref,
            due_state=due_state,
        ).order_by(IncidentRecord.updated_at.desc(), IncidentRecord.id.asc())
        statement = statement.offset(offset).limit(limit)
        return self._session.scalars(statement).all()

    def count_collection(
        self,
        *,
        machine_id: UUID | None = None,
        status: IncidentStatus | None = None,
        severity: str | None = None,
        owner_ref: str | None = None,
        due_state: str | None = None,
    ) -> int:
        statement = self._apply_collection_filters(
            select(func.count()).select_from(IncidentRecord),
            machine_id=machine_id,
            status=status,
            severity=severity,
            owner_ref=owner_ref,
            due_state=due_state,
        )
        return int(self._session.scalar(statement) or 0)

    def count_by_status(self) -> dict[IncidentStatus, int]:
        rows = self._session.execute(
            select(IncidentRecord.status, func.count())
            .group_by(IncidentRecord.status)
            .order_by(IncidentRecord.status)
        ).all()
        return {status: int(count) for status, count in rows}


class SQLAlchemyIncidentEvidenceLinkRepository(
    _RepositoryBase[IncidentEvidenceLinkRecord]
):
    record_type = IncidentEvidenceLinkRecord

    def list_for_incident(
        self, incident_id: UUID
    ) -> Sequence[IncidentEvidenceLinkRecord]:
        statement = (
            select(IncidentEvidenceLinkRecord)
            .where(IncidentEvidenceLinkRecord.incident_id == incident_id)
            .order_by(
                IncidentEvidenceLinkRecord.linked_at,
                IncidentEvidenceLinkRecord.id,
            )
        )
        return self._session.scalars(statement).all()

    def list_active_for_incident(
        self, incident_id: UUID
    ) -> Sequence[IncidentEvidenceLinkRecord]:
        statement = (
            select(IncidentEvidenceLinkRecord)
            .where(
                IncidentEvidenceLinkRecord.incident_id == incident_id,
                IncidentEvidenceLinkRecord.is_active.is_(True),
            )
            .order_by(
                IncidentEvidenceLinkRecord.linked_at,
                IncidentEvidenceLinkRecord.id,
            )
        )
        return self._session.scalars(statement).all()

    def list_active_for_evidence(
        self, evidence_event_id: UUID
    ) -> Sequence[IncidentEvidenceLinkRecord]:
        statement = (
            select(IncidentEvidenceLinkRecord)
            .where(
                IncidentEvidenceLinkRecord.evidence_event_id == evidence_event_id,
                IncidentEvidenceLinkRecord.is_active.is_(True),
            )
            .order_by(
                IncidentEvidenceLinkRecord.incident_id,
                IncidentEvidenceLinkRecord.id,
            )
        )
        return self._session.scalars(statement).all()




class SQLAlchemyIncidentAuditEventRepository(
    _RepositoryBase[IncidentAuditEventRecord]
):
    """Append-only in its public persistence API."""

    record_type = IncidentAuditEventRecord

    def list_for_incident(
        self, incident_id: UUID
    ) -> Sequence[IncidentAuditEventRecord]:
        statement = (
            select(IncidentAuditEventRecord)
            .where(IncidentAuditEventRecord.incident_id == incident_id)
            .order_by(
                IncidentAuditEventRecord.occurred_at,
                IncidentAuditEventRecord.id,
            )
        )
        return self._session.scalars(statement).all()


class SQLAlchemyVerificationRuleRepository(_RepositoryBase[VerificationRuleRecord]):
    record_type = VerificationRuleRecord

    def get_by_identifier(self, identifier: str) -> VerificationRuleRecord | None:
        statement = select(VerificationRuleRecord).where(
            VerificationRuleRecord.identifier == identifier
        )
        return self._session.scalar(statement)


class SQLAlchemyVerificationRunRepository(_RepositoryBase[VerificationRunRecord]):
    record_type = VerificationRunRecord

    def list_for_incident(
        self, incident_id: UUID
    ) -> Sequence[VerificationRunRecord]:
        statement = (
            select(VerificationRunRecord)
            .where(VerificationRunRecord.incident_id == incident_id)
            .order_by(VerificationRunRecord.started_at, VerificationRunRecord.id)
        )
        return self._session.scalars(statement).all()

    def list_for_rule(
        self, verification_rule_id: UUID
    ) -> Sequence[VerificationRunRecord]:
        statement = (
            select(VerificationRunRecord)
            .where(
                VerificationRunRecord.verification_rule_id == verification_rule_id
            )
            .order_by(VerificationRunRecord.started_at, VerificationRunRecord.id)
        )
        return self._session.scalars(statement).all()




class SQLAlchemyVerificationEvidenceRepository(
    _RepositoryBase[VerificationEvidenceRecord]
):
    record_type = VerificationEvidenceRecord

    def list_for_run(
        self, verification_run_id: UUID
    ) -> Sequence[VerificationEvidenceRecord]:
        statement = (
            select(VerificationEvidenceRecord)
            .where(
                VerificationEvidenceRecord.verification_run_id == verification_run_id
            )
            .order_by(VerificationEvidenceRecord.id)
        )
        return self._session.scalars(statement).all()

