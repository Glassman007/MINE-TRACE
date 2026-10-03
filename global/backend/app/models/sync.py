from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SessionReportRecord(Base):
    __tablename__ = "session_reports"
    __table_args__ = (
        UniqueConstraint("source_machine_id", "session_id", "report_revision", name="uq_session_report_revision"),
        UniqueConstraint("report_id", name="uq_session_reports_report_id"),
        Index("ix_session_reports_session_revision", "session_id", "report_revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    report_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_machine_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    report_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    checksum: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class SyncReceiptRecord(Base):
    __tablename__ = "sync_receipts"
    __table_args__ = (
        UniqueConstraint("source_machine_id", "package_id", "report_revision", name="uq_sync_receipt_package_revision"),
        Index("ix_sync_receipts_machine_session", "source_machine_id", "session_id", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    package_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_machine_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False)
    report_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    checksum: Mapped[str] = mapped_column(String(255), nullable=False)
    acknowledgement_status: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncConflictRecord(Base):
    __tablename__ = "sync_conflicts"
    __table_args__ = (Index("ix_sync_conflicts_machine_session", "source_machine_id", "session_id", "detected_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_machine_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False)
    incoming_package_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    existing_receipt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sync_receipts.id", ondelete="RESTRICT"), nullable=True)
    conflict_type: Mapped[str] = mapped_column(String(64), nullable=False)
    incoming_report_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    existing_report_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    incoming_checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    existing_checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    incoming_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}")
    existing_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolution_status: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UNRESOLVED")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
