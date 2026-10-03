"""Exact fleet queries over canonical relational storage only."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.domain.enums import IncidentStatus
from app.models import (
    EvidenceEventRecord,
    IncidentRecord,
    MachineRecord,
    MaintenanceActionRecord,
    OperatingSessionRecord,
    SyncConflictRecord,
    SyncReceiptRecord,
    VerificationRunRecord,
)
from app.schemas.analytics import (
    AnalyticsBucketsResponse,
    AnalyticsCountBucket,
    AnalyticsSummaryResponse,
    AnalyticsTrendPoint,
    AnalyticsTrendResponse,
)
from app.schemas.fleet import (
    FleetIncidentCollectionResponse,
    FleetIncidentItem,
    FleetMachineCollectionResponse,
    FleetMachineItem,
    FleetOverviewResponse,
    FleetSessionItem,
    MachineSessionsResponse,
)
from app.schemas.maintenance import MaintenanceQueueItem, MaintenanceQueueResponse
from app.schemas.sync_reads import (
    MachineSyncHealthItem,
    OptionalCapabilityState,
    SyncConflictCollectionResponse,
    SyncConflictItem,
    SyncHealthResponse,
)

UNRESOLVED_INCIDENT_STATUSES = (
    IncidentStatus.OPEN,
    IncidentStatus.VERIFYING,
    IncidentStatus.RECURRED,
)


class FleetNotFoundError(LookupError):
    pass


def _session_item(row: OperatingSessionRecord) -> FleetSessionItem:
    return FleetSessionItem(
        session_id=row.id,
        machine_id=row.machine_id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        state=row.state,
        operating_hours=row.operating_hours,
        latest_report_revision=row.latest_report_revision,
        ingested_at=row.ingested_at,
        updated_at=row.updated_at,
    )


class FleetQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _latest_receipt(self, machine_id: UUID) -> SyncReceiptRecord | None:
        return self.session.scalar(
            select(SyncReceiptRecord)
            .where(SyncReceiptRecord.source_machine_id == machine_id)
            .order_by(SyncReceiptRecord.received_at.desc(), SyncReceiptRecord.id.desc())
            .limit(1)
        )

    def _machine_item(self, row: MachineRecord) -> FleetMachineItem:
        receipt = self._latest_receipt(row.id)
        return FleetMachineItem(
            id=row.id,
            display_name=row.display_name,
            asset_code=row.asset_code,
            machine_type=row.machine_type,
            manufacturer=row.manufacturer,
            model=row.model,
            site_name=row.site_name,
            site_area=row.site_area,
            latest_sync_received_at=receipt.received_at if receipt else None,
            latest_acknowledged_at=receipt.acknowledged_at if receipt else None,
            latest_acknowledgement_status=receipt.acknowledgement_status if receipt else None,
            latest_report_revision=receipt.report_revision if receipt else None,
        )

    def list_machines(
        self,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        site: str | None = None,
        machine_type: str | None = None,
        model: str | None = None,
    ) -> FleetMachineCollectionResponse:
        conditions = []
        if search and (needle := search.strip().lower()):
            conditions.append(
                or_(
                    func.lower(MachineRecord.display_name).contains(needle),
                    func.lower(MachineRecord.asset_code).contains(needle),
                    func.lower(MachineRecord.machine_type).contains(needle),
                    func.lower(MachineRecord.model).contains(needle),
                    func.lower(MachineRecord.site_name).contains(needle),
                )
            )
        if site is not None:
            conditions.append(MachineRecord.site_name == site)
        if machine_type is not None:
            conditions.append(MachineRecord.machine_type == machine_type)
        if model is not None:
            conditions.append(MachineRecord.model == model)
        stmt = select(MachineRecord)
        count_stmt = select(func.count()).select_from(MachineRecord)
        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)
        rows = self.session.scalars(
            stmt.order_by(
                case((MachineRecord.display_name.is_(None), 1), else_=0),
                MachineRecord.display_name.asc(),
                MachineRecord.id.asc(),
            ).offset(offset).limit(limit)
        ).all()
        return FleetMachineCollectionResponse(
            items=[self._machine_item(row) for row in rows],
            total=int(self.session.scalar(count_stmt) or 0),
            offset=offset,
            limit=limit,
        )

    def get_machine(self, machine_id: UUID) -> FleetMachineItem:
        row = self.session.get(MachineRecord, machine_id)
        if row is None:
            raise FleetNotFoundError(f"unknown machine: {machine_id}")
        return self._machine_item(row)

    def list_sessions(self, machine_id: UUID, *, offset: int, limit: int) -> MachineSessionsResponse:
        if self.session.get(MachineRecord, machine_id) is None:
            raise FleetNotFoundError(f"unknown machine: {machine_id}")
        base = OperatingSessionRecord.machine_id == machine_id
        rows = self.session.scalars(
            select(OperatingSessionRecord)
            .where(base)
            .order_by(OperatingSessionRecord.started_at.desc(), OperatingSessionRecord.id.asc())
            .offset(offset).limit(limit)
        ).all()
        total = int(self.session.scalar(select(func.count()).select_from(OperatingSessionRecord).where(base)) or 0)
        return MachineSessionsResponse(
            machine_id=machine_id,
            items=[_session_item(row) for row in rows],
            total=total,
            offset=offset,
            limit=limit,
        )

    def list_incidents(
        self,
        *,
        offset: int,
        limit: int,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        status: IncidentStatus | None = None,
        model: str | None = None,
        site: str | None = None,
    ) -> FleetIncidentCollectionResponse:
        conditions = []
        if machine_id is not None:
            conditions.append(IncidentRecord.machine_id == machine_id)
        if component_id is not None:
            conditions.append(IncidentRecord.component_id == component_id)
        activity_time = func.coalesce(IncidentRecord.last_seen_at, IncidentRecord.first_seen_at, IncidentRecord.created_at)
        if start is not None:
            conditions.append(activity_time >= start)
        if end is not None:
            conditions.append(activity_time <= end)
        if status is not None:
            conditions.append(IncidentRecord.status == status)
        if model is not None:
            conditions.append(MachineRecord.model == model)
        if site is not None:
            conditions.append(MachineRecord.site_name == site)
        stmt = select(IncidentRecord, MachineRecord).join(MachineRecord, MachineRecord.id == IncidentRecord.machine_id)
        count_stmt = select(func.count()).select_from(IncidentRecord).join(MachineRecord, MachineRecord.id == IncidentRecord.machine_id)
        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)
        rows = self.session.execute(
            stmt.order_by(activity_time.desc(), IncidentRecord.id.asc()).offset(offset).limit(limit)
        ).all()
        return FleetIncidentCollectionResponse(
            items=[
                FleetIncidentItem(
                    incident_id=incident.id,
                    machine_id=incident.machine_id,
                    component_id=incident.component_id,
                    status=incident.status,
                    owner_ref=incident.owner_ref,
                    severity=incident.severity,
                    due_state=incident.due_state,
                    due_time=incident.due_time,
                    first_seen_at=incident.first_seen_at,
                    last_seen_at=incident.last_seen_at,
                    source_report_revision=incident.source_report_revision,
                    machine_model=machine.model,
                    site_name=machine.site_name,
                    created_at=incident.created_at,
                    updated_at=incident.updated_at,
                )
                for incident, machine in rows
            ],
            total=int(self.session.scalar(count_stmt) or 0),
            offset=offset,
            limit=limit,
        )

    def overview(self, *, recent_session_limit: int = 10) -> FleetOverviewResponse:
        recent = self.session.scalars(
            select(OperatingSessionRecord)
            .order_by(OperatingSessionRecord.started_at.desc(), OperatingSessionRecord.id.asc())
            .limit(recent_session_limit)
        ).all()
        verification_rows = self.session.execute(
            select(VerificationRunRecord.result, func.count())
            .group_by(VerificationRunRecord.result)
        ).all()
        verification_states = {
            (result.value if result is not None else "PENDING"): int(count)
            for result, count in verification_rows
        }
        ack_rows = self.session.execute(
            select(SyncReceiptRecord.acknowledgement_status, func.count())
            .group_by(SyncReceiptRecord.acknowledgement_status)
        ).all()
        latest_received = self.session.scalar(select(func.max(SyncReceiptRecord.received_at)))
        latest_ack = self.session.scalar(select(func.max(SyncReceiptRecord.acknowledged_at)))
        unresolved_conflicts = int(
            self.session.scalar(
                select(func.count()).select_from(SyncConflictRecord).where(SyncConflictRecord.resolution_status == "UNRESOLVED")
            ) or 0
        )
        return FleetOverviewResponse(
            fleet_machine_count=int(self.session.scalar(select(func.count()).select_from(MachineRecord)) or 0),
            recent_sessions=[_session_item(row) for row in recent],
            unresolved_incident_count=int(
                self.session.scalar(
                    select(func.count()).select_from(IncidentRecord).where(IncidentRecord.status.in_(UNRESOLVED_INCIDENT_STATUSES))
                ) or 0
            ),
            verification_states=verification_states,
            latest_sync_received_at=latest_received,
            latest_acknowledged_at=latest_ack,
            acknowledgement_status_counts={str(status): int(count) for status, count in ack_rows},
            unresolved_sync_conflicts=unresolved_conflicts,
        )

    def maintenance_queue(self, *, offset: int, limit: int) -> MaintenanceQueueResponse:
        condition = IncidentRecord.status.in_(UNRESOLVED_INCIDENT_STATUSES)
        stmt = (
            select(IncidentRecord, MachineRecord)
            .join(MachineRecord, MachineRecord.id == IncidentRecord.machine_id)
            .where(condition)
            .order_by(
                case((IncidentRecord.due_time.is_(None), 1), else_=0),
                IncidentRecord.due_time.asc(),
                IncidentRecord.updated_at.asc(),
                IncidentRecord.id.asc(),
            )
            .offset(offset).limit(limit)
        )
        rows = self.session.execute(stmt).all()
        items: list[MaintenanceQueueItem] = []
        for incident, machine in rows:
            action = self.session.scalar(
                select(MaintenanceActionRecord)
                .where(MaintenanceActionRecord.incident_id == incident.id)
                .order_by(MaintenanceActionRecord.original_timestamp.desc(), MaintenanceActionRecord.id.desc())
                .limit(1)
            )
            verification = self.session.scalar(
                select(VerificationRunRecord)
                .where(VerificationRunRecord.incident_id == incident.id)
                .order_by(VerificationRunRecord.started_at.desc(), VerificationRunRecord.id.desc())
                .limit(1)
            )
            items.append(
                MaintenanceQueueItem(
                    incident_id=incident.id,
                    machine_id=incident.machine_id,
                    component_id=incident.component_id,
                    incident_status=incident.status,
                    due_state=incident.due_state,
                    due_time=incident.due_time,
                    site_name=machine.site_name,
                    machine_model=machine.model,
                    latest_maintenance_action_id=action.id if action else None,
                    latest_maintenance_action_type=action.action_type if action else None,
                    latest_maintenance_at=action.original_timestamp if action else None,
                    latest_verification_run_id=verification.id if verification else None,
                    latest_verification_result=verification.result if verification else None,
                    latest_verification_completed_at=verification.completed_at if verification else None,
                    verification_required=incident.status == IncidentStatus.VERIFYING,
                    updated_at=incident.updated_at,
                )
            )
        total = int(self.session.scalar(select(func.count()).select_from(IncidentRecord).where(condition)) or 0)
        return MaintenanceQueueResponse(items=items, total=total, offset=offset, limit=limit)

    def analytics_summary(self) -> AnalyticsSummaryResponse:
        def count(model, *conditions) -> int:
            stmt = select(func.count()).select_from(model)
            if conditions:
                stmt = stmt.where(*conditions)
            return int(self.session.scalar(stmt) or 0)
        verifications = count(VerificationRunRecord)
        completed = count(VerificationRunRecord, VerificationRunRecord.completed_at.is_not(None))
        return AnalyticsSummaryResponse(
            machines=count(MachineRecord),
            sessions=count(OperatingSessionRecord),
            incidents=count(IncidentRecord),
            unresolved_incidents=count(IncidentRecord, IncidentRecord.status.in_(UNRESOLVED_INCIDENT_STATUSES)),
            evidence=count(EvidenceEventRecord),
            maintenance_actions=count(MaintenanceActionRecord),
            verification_runs=verifications,
            completed_verification_runs=completed,
            verification_completion_rate=(completed / verifications if verifications else None),
            sync_conflicts_unresolved=count(SyncConflictRecord, SyncConflictRecord.resolution_status == "UNRESOLVED"),
        )

    def analytics_incidents_by_status(self) -> AnalyticsBucketsResponse:
        rows = self.session.execute(
            select(IncidentRecord.status, func.count()).group_by(IncidentRecord.status).order_by(IncidentRecord.status)
        ).all()
        return AnalyticsBucketsResponse(items=[AnalyticsCountBucket(key=status.value, count=int(count)) for status, count in rows])

    def analytics_incidents_by_site(self) -> AnalyticsBucketsResponse:
        rows = self.session.execute(
            select(MachineRecord.site_name, func.count(IncidentRecord.id))
            .join(IncidentRecord, IncidentRecord.machine_id == MachineRecord.id)
            .group_by(MachineRecord.site_name)
            .order_by(MachineRecord.site_name)
        ).all()
        return AnalyticsBucketsResponse(items=[AnalyticsCountBucket(key=site or "UNSPECIFIED", count=int(count)) for site, count in rows])

    def analytics_incident_trend(self) -> AnalyticsTrendResponse:
        activity_time = func.coalesce(IncidentRecord.first_seen_at, IncidentRecord.created_at)
        rows = self.session.execute(
            select(func.date(activity_time), func.count())
            .group_by(func.date(activity_time))
            .order_by(func.date(activity_time))
        ).all()
        return AnalyticsTrendResponse(items=[AnalyticsTrendPoint(day=str(day), count=int(count)) for day, count in rows if day is not None])

    def sync_health(
        self,
        *,
        semantic_status: str,
        semantic_reason: str | None,
        embedding_status: str,
        embedding_reason: str | None,
        ai_status: str,
        ai_reason: str | None,
        stale_after_hours: float | None,
    ) -> SyncHealthResponse:
        now = datetime.now(timezone.utc)
        machines = self.session.scalars(select(MachineRecord).order_by(MachineRecord.id)).all()
        items: list[MachineSyncHealthItem] = []
        for machine in machines:
            receipt = self._latest_receipt(machine.id)
            latest_session = self.session.scalar(
                select(OperatingSessionRecord)
                .where(OperatingSessionRecord.machine_id == machine.id)
                .order_by(OperatingSessionRecord.started_at.desc(), OperatingSessionRecord.id.desc())
                .limit(1)
            )
            conflict_count = int(
                self.session.scalar(
                    select(func.count()).select_from(SyncConflictRecord).where(
                        SyncConflictRecord.source_machine_id == machine.id,
                        SyncConflictRecord.resolution_status == "UNRESOLVED",
                    )
                ) or 0
            )
            age_seconds = None
            stale = None
            if receipt is not None:
                received = receipt.received_at
                if received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
                age_seconds = max(0.0, (now - received).total_seconds())
                if stale_after_hours is not None:
                    stale = age_seconds > stale_after_hours * 3600
            elif stale_after_hours is not None:
                stale = True
            items.append(
                MachineSyncHealthItem(
                    machine_id=machine.id,
                    latest_session_id=latest_session.id if latest_session else None,
                    latest_report_revision=receipt.report_revision if receipt else (latest_session.latest_report_revision if latest_session else None),
                    latest_receipt_id=receipt.id if receipt else None,
                    latest_received_at=receipt.received_at if receipt else None,
                    latest_acknowledged_at=receipt.acknowledged_at if receipt else None,
                    acknowledgement_status=receipt.acknowledgement_status if receipt else None,
                    unresolved_conflicts=conflict_count,
                    age_seconds=age_seconds,
                    stale=stale,
                )
            )
        total_conflicts = int(self.session.scalar(select(func.count()).select_from(SyncConflictRecord).where(SyncConflictRecord.resolution_status == "UNRESOLVED")) or 0)
        return SyncHealthResponse(
            machines=items,
            unresolved_conflicts=total_conflicts,
            semantic=OptionalCapabilityState(status=semantic_status, reason=semantic_reason),
            embeddings=OptionalCapabilityState(status=embedding_status, reason=embedding_reason),
            ai=OptionalCapabilityState(status=ai_status, reason=ai_reason),
            stale_after_hours=stale_after_hours,
        )

    def sync_conflicts(self, *, offset: int, limit: int, unresolved_only: bool) -> SyncConflictCollectionResponse:
        condition = SyncConflictRecord.resolution_status == "UNRESOLVED" if unresolved_only else None
        stmt = select(SyncConflictRecord)
        count_stmt = select(func.count()).select_from(SyncConflictRecord)
        if condition is not None:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)
        rows = self.session.scalars(
            stmt.order_by(SyncConflictRecord.detected_at.desc(), SyncConflictRecord.id.asc()).offset(offset).limit(limit)
        ).all()
        return SyncConflictCollectionResponse(
            items=[
                SyncConflictItem(
                    conflict_id=row.id,
                    source_machine_id=row.source_machine_id,
                    session_id=row.session_id,
                    incoming_package_id=row.incoming_package_id,
                    existing_receipt_id=row.existing_receipt_id,
                    conflict_type=row.conflict_type,
                    incoming_report_revision=row.incoming_report_revision,
                    existing_report_revision=row.existing_report_revision,
                    incoming_checksum=row.incoming_checksum,
                    existing_checksum=row.existing_checksum,
                    incoming_metadata=row.incoming_metadata,
                    existing_metadata=row.existing_metadata,
                    detected_at=row.detected_at,
                    resolution_status=row.resolution_status,
                    resolved_at=row.resolved_at,
                    resolution_notes=row.resolution_notes,
                ) for row in rows
            ],
            total=int(self.session.scalar(count_stmt) or 0),
            offset=offset,
            limit=limit,
        )
