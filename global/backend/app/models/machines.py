from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MachineRecord(Base):
    __tablename__ = "machines"
    __table_args__ = (UniqueConstraint("asset_code", name="uq_machines_asset_code"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asset_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    machine_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    site_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    site_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    components = relationship("ComponentRecord", back_populates="machine")
    sessions = relationship("OperatingSessionRecord", back_populates="machine")
    incidents = relationship("IncidentRecord", back_populates="machine")


class ComponentRecord(Base):
    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint("id", "machine_id", name="uq_components_id_machine_id"),
        Index("ix_components_machine_id", "machine_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    machine_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    component_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)

    machine = relationship("MachineRecord", back_populates="components")
