from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, JSON, String, Text, UniqueConstraint, Uuid, event, func, text
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import IncidentAuditAction, IncidentEvidenceRelationshipType, IncidentStatus


class IncidentRecord(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_machine_status", "machine_id", "status"),
        Index("ix_incidents_component_status", "component_id", "status"),
        Index("ix_incidents_last_seen", "last_seen_at"),
    )

    # Stable edge incident identity is preserved as the canonical UUID.
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    machine_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    component_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("components.id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[IncidentStatus] = mapped_column(Enum(IncidentStatus, native_enum=False, create_constraint=True, validate_strings=True, name="incident_status"), nullable=False)
    owner_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    due_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    due_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_report_revision: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    machine = relationship("MachineRecord", back_populates="incidents")


class IncidentSessionLinkRecord(Base):
    __tablename__ = "incident_session_links"
    __table_args__ = (
        UniqueConstraint("incident_id", "session_id", name="uq_incident_session_link"),
        Index("ix_incident_session_links_session", "session_id", "incident_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False)
    source_report_revision: Mapped[int | None] = mapped_column(nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IncidentEvidenceLinkRecord(Base):
    __tablename__ = "incident_evidence_links"
    __table_args__ = (
        CheckConstraint(
            "(is_active AND unlinked_at IS NULL) OR ((NOT is_active) AND unlinked_at IS NOT NULL)",
            name="active_unlinked_timestamp_consistent",
        ),
        Index("ix_incident_evidence_links_incident_retrieval", "incident_id", "linked_at"),
        Index("ix_incident_evidence_links_evidence_retrieval", "evidence_event_id", "linked_at"),
        Index(
            "ix_incident_evidence_links_active_incident",
            "incident_id",
            "evidence_event_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False)
    evidence_event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("evidence_events.id", ondelete="RESTRICT"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    relationship_type: Mapped[IncidentEvidenceRelationshipType] = mapped_column(Enum(IncidentEvidenceRelationshipType, native_enum=False, create_constraint=True, validate_strings=True, name="incident_evidence_relationship_type"), nullable=False)
    deterministic_rule_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    link_reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_report_revision: Mapped[int | None] = mapped_column(nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IncidentAuditEventRecord(Base):
    """Synchronized append-only audit detail retained for canonical read history."""

    __tablename__ = "incident_audit_events"
    __table_args__ = (Index("ix_incident_audit_events_incident_timeline", "incident_id", "occurred_at", "id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[IncidentAuditAction] = mapped_column(Enum(IncidentAuditAction, native_enum=False, create_constraint=True, validate_strings=True, name="incident_audit_action"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default=text("'{}'"))


class AppendOnlyAuditViolation(RuntimeError):
    pass


@event.listens_for(IncidentAuditEventRecord, "before_update")
def _prevent_audit_update(_mapper: Mapper[IncidentAuditEventRecord], _connection: object, _target: IncidentAuditEventRecord) -> None:
    raise AppendOnlyAuditViolation("incident audit events are append-only")


@event.listens_for(IncidentAuditEventRecord, "before_delete")
def _prevent_audit_delete(_mapper: Mapper[IncidentAuditEventRecord], _connection: object, _target: IncidentAuditEventRecord) -> None:
    raise AppendOnlyAuditViolation("incident audit events are append-only")
