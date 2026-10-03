from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import VerificationRuleType, VerificationRunResult


class VerificationRuleRecord(Base):
    """Synchronized rule metadata only; the global service does not execute it."""

    __tablename__ = "verification_rules"
    __table_args__ = (UniqueConstraint("identifier", name="uq_verification_rules_identifier"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rule_type: Mapped[VerificationRuleType | None] = mapped_column(Enum(VerificationRuleType, native_enum=False, create_constraint=True, validate_strings=True, name="verification_rule_type"), nullable=True)
    window_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class VerificationRunRecord(Base):
    __tablename__ = "verification_runs"
    __table_args__ = (
        Index("ix_verification_runs_incident_lookup", "incident_id", "started_at"),
        Index("ix_verification_runs_session_lookup", "session_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False)
    session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=True)
    source_machine_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    verification_rule_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("verification_rules.id", ondelete="RESTRICT"), nullable=True)
    rule_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[VerificationRunResult | None] = mapped_column(Enum(VerificationRunResult, native_enum=False, create_constraint=True, validate_strings=True, name="verification_run_result"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingestion_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source_report_revision: Mapped[int | None] = mapped_column(nullable=True)
    outcome_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}")


class VerificationEvidenceRecord(Base):
    __tablename__ = "verification_evidence"
    __table_args__ = (
        UniqueConstraint("verification_run_id", "evidence_event_id", name="uq_verification_evidence_run_evidence"),
        Index("ix_verification_evidence_run_id", "verification_run_id"),
        Index("ix_verification_evidence_evidence_event_id", "evidence_event_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    verification_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("verification_runs.id", ondelete="RESTRICT"), nullable=False)
    evidence_event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("evidence_events.id", ondelete="RESTRICT"), nullable=False)
