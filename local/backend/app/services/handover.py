"""Deterministic shift handover snapshots over authoritative incident state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.core.time import normalize_to_utc, restore_utc
from app.domain.enums import IncidentAuditAction, IncidentStatus
from app.models import HandoverItemRecord, HandoverPacketRecord, IncidentAuditEventRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork, UnitOfWork
from app.schemas.handover import HandoverItemOutput, HandoverPacketResponse


HANDOVER_STATUSES: tuple[IncidentStatus, ...] = (
    IncidentStatus.OPEN,
    IncidentStatus.VERIFYING,
    IncidentStatus.RECURRED,
)


class HandoverError(RuntimeError):
    pass


class UnknownHandoverError(HandoverError):
    pass


class HandoverAlreadyAcknowledgedError(HandoverError):
    pass


class CorruptHandoverSnapshotError(HandoverError):
    pass


@dataclass(frozen=True, slots=True)
class HandoverCreationResult:
    packet_id: UUID


class HandoverService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] = SQLAlchemyUnitOfWork,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def create_handover(self, *, created_at: datetime | None = None) -> HandoverPacketResponse:
        snapshot_time = normalize_to_utc(created_at or self._clock())
        with self._uow_factory() as uow:
            packet = HandoverPacketRecord(
                id=uuid4(),
                created_at=snapshot_time,
                acknowledged_at=None,
            )
            uow.handover_packets.add(packet)
            uow.flush()

            for incident in uow.incidents.list_by_statuses(HANDOVER_STATUSES):
                uow.handover_items.add(
                    HandoverItemRecord(
                        id=uuid4(),
                        handover_packet_id=packet.id,
                        incident_id=incident.id,
                        severity_snapshot=incident.severity,
                        owner_ref_snapshot=incident.owner_ref,
                        status_snapshot=incident.status,
                        due_state_snapshot=incident.due_state,
                        due_time_snapshot=incident.due_time,
                    )
                )
            uow.flush()
            response = self._view(uow, packet)
            uow.commit()
            return response

    def get_handover(self, packet_id: UUID) -> HandoverPacketResponse:
        with self._uow_factory() as uow:
            packet = uow.handover_packets.get(packet_id)
            if packet is None:
                raise UnknownHandoverError(f"unknown handover packet: {packet_id}")
            return self._view(uow, packet)

    def acknowledge(
        self,
        packet_id: UUID,
        *,
        acknowledged_at: datetime | None = None,
    ) -> HandoverPacketResponse:
        at = normalize_to_utc(acknowledged_at or self._clock())
        with self._uow_factory() as uow:
            packet = uow.handover_packets.get(packet_id)
            if packet is None:
                raise UnknownHandoverError(f"unknown handover packet: {packet_id}")
            if packet.acknowledged_at is not None:
                raise HandoverAlreadyAcknowledgedError(
                    f"handover packet already acknowledged: {packet_id}"
                )

            items = tuple(uow.handover_items.list_for_packet(packet.id))
            packet.acknowledged_at = at

            for item in items:
                uow.incident_audit_events.add(
                    IncidentAuditEventRecord(
                        id=uuid4(),
                        incident_id=item.incident_id,
                        action=IncidentAuditAction.HANDOVER_ACKNOWLEDGED,
                        occurred_at=at,
                        payload={"handover_packet_id": str(packet.id)},
                    )
                )

            # Packet acknowledgement and all incident audit entries are one transaction.
            uow.flush()
            response = self._view(uow, packet, items=items)
            uow.commit()
            return response

    def _view(
        self,
        uow: UnitOfWork,
        packet: HandoverPacketRecord,
        *,
        items: tuple[HandoverItemRecord, ...] | None = None,
    ) -> HandoverPacketResponse:
        records = items or tuple(uow.handover_items.list_for_packet(packet.id))
        output: list[HandoverItemOutput] = []
        for item in records:
            if item.status_snapshot is None:
                # Legacy rows predating snapshot semantics cannot be truthfully
                # reconstructed from current incident state without rewriting history.
                raise CorruptHandoverSnapshotError(
                    f"handover item lacks historical status snapshot: {item.id}"
                )
            output.append(
                HandoverItemOutput(
                    id=item.id,
                    incident_id=item.incident_id,
                    severity=item.severity_snapshot,
                    owner_ref=item.owner_ref_snapshot,
                    status=item.status_snapshot,
                    due_state=item.due_state_snapshot,
                    due_time=restore_utc(item.due_time_snapshot),
                )
            )
        return HandoverPacketResponse(
            id=packet.id,
            created_at=restore_utc(packet.created_at),
            acknowledged_at=restore_utc(packet.acknowledged_at),
            items=output,
        )
