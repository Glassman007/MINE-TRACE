from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, ForeignKeyConstraint, Index, JSON, String, UniqueConstraint, Uuid, event, func
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.db.base import Base
from app.domain.enums import ContextQuality


class EvidenceEventRecord(Base):
    """Canonical synchronized evidence preserving the stable edge evidence UUID."""

    __tablename__ = "evidence_events"
    __table_args__ = (
        UniqueConstraint("source_machine_id", "source_type", "original_source_record_id", name="uq_evidence_source_identity"),
        ForeignKeyConstraint(["component_id", "machine_id"], ["components.id", "components.machine_id"], name="fk_evidence_events_component_machine", ondelete="RESTRICT"),
        Index("ix_evidence_events_machine_timeline", "machine_id", "original_timestamp", "id"),
        Index("ix_evidence_events_session_timeline", "session_id", "original_timestamp", "id"),
        Index("ix_evidence_events_component_timeline", "component_id", "original_timestamp", "id"),
        Index("ix_evidence_events_ingestion_timestamp", "ingestion_timestamp"),
    )

    # This UUID is the stable upstream evidence identity; the global service does
    # not mint a replacement identity during synchronization.
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    machine_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    source_machine_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=True)
    component_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    original_source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source_report_revision: Mapped[int | None] = mapped_column(nullable=True)
    canonical_event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)


class EvidenceAttachmentRecord(Base):
    """Optional synchronized raw-evidence reference; canonical truth remains relational."""

    __tablename__ = "evidence_attachments"
    __table_args__ = (
        Index("ix_evidence_attachments_evidence_event_id", "evidence_event_id"),
        CheckConstraint("file_size IS NULL OR file_size >= 0", name="file_size_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    evidence_event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("evidence_events.id", ondelete="RESTRICT"), nullable=False)
    attachment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storage_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContextSnapshotRecord(Base):
    __tablename__ = "context_snapshots"
    __table_args__ = (Index("ix_context_snapshots_evidence_event_id", "evidence_event_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    evidence_event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("evidence_events.id", ondelete="RESTRICT"), nullable=False)
    quality: Mapped[ContextQuality | None] = mapped_column(Enum(ContextQuality, native_enum=False, create_constraint=True, validate_strings=True, name="context_quality"), nullable=True)
    snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ImmutableContextSnapshotViolation(RuntimeError):
    pass


@event.listens_for(ContextSnapshotRecord, "before_update")
def _prevent_context_snapshot_update(_mapper: Mapper[ContextSnapshotRecord], _connection: object, _target: ContextSnapshotRecord) -> None:
    raise ImmutableContextSnapshotViolation("context snapshots are historical and must not be overwritten")


@event.listens_for(ContextSnapshotRecord, "before_delete")
def _prevent_context_snapshot_delete(_mapper: Mapper[ContextSnapshotRecord], _connection: object, _target: ContextSnapshotRecord) -> None:
    raise ImmutableContextSnapshotViolation("context snapshots are historical and must not be overwritten")
