from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MaintenanceActionRecord(Base):
    __tablename__ = "maintenance_actions"
    __table_args__ = (
        Index("ix_maintenance_actions_incident_time", "incident_id", "original_timestamp"),
        Index("ix_maintenance_actions_machine_time", "machine_id", "original_timestamp"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    machine_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    incident_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False)
    session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=True)
    component_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("components.id", ondelete="RESTRICT"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source_report_revision: Mapped[int | None] = mapped_column(nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}")
