"""Explicit deterministic development/demo seed for MINE-TRACE.

Run only on an already-migrated development/test database::

    python -m app.seed
    python -m app.seed --reset
    python -m app.seed --reset --anchor 2026-10-03T12:00:00Z

Nothing in normal application startup imports or invokes this module.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings
from app.core.time import normalize_to_utc
from app.db.base import Base
from app.db.session import create_database_engine
from app.domain.enums import (
    ContextQuality,
    EvidenceSourceType,
    IncidentAuditAction,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
    VerificationRuleType,
    VerificationRunResult,
)
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
    VerificationEvidenceRecord,
    VerificationRuleRecord,
    VerificationRunRecord,
)

SEED_NAMESPACE = UUID("9f46666b-9e65-5b40-b7d9-257cc5a06651")
SEED_VERSION = "mine-trace-demo-v1"


def seed_id(name: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"{SEED_VERSION}:{name}")


MACHINE_IDS = {
    "haul_truck_01": seed_id("machine:haul-truck-01"),
    "excavator_01": seed_id("machine:excavator-01"),
    "loader_01": seed_id("machine:loader-01"),
}
COMPONENT_IDS = {
    "haul_hydraulics": seed_id("component:haul-truck-01:hydraulics"),
    "haul_brakes": seed_id("component:haul-truck-01:brakes"),
    "excavator_hydraulics": seed_id("component:excavator-01:hydraulics"),
    "loader_cooling": seed_id("component:loader-01:cooling"),
}
EVIDENCE_IDS = {
    "hydraulic_exact_history": seed_id("evidence:hydraulic-exact-history"),
    "hydraulic_semantic_history": seed_id("evidence:hydraulic-semantic-history"),
    "hydraulic_initial": seed_id("evidence:hydraulic-initial"),
    "hydraulic_recurrence": seed_id("evidence:hydraulic-recurrence"),
    "maintenance_filter": seed_id("evidence:maintenance-filter"),
    "operator_audio": seed_id("evidence:operator-audio"),
    "brake_exact_history": seed_id("evidence:brake-exact-history"),
    "brake_primary": seed_id("evidence:brake-primary"),
    "cooling_primary": seed_id("evidence:cooling-primary"),
    "excavator_initial": seed_id("evidence:excavator-initial"),
    "excavator_recurrence": seed_id("evidence:excavator-recurrence"),
}
INCIDENT_IDS = {
    "hydraulic_open_with_recurrence": seed_id("incident:hydraulic-open-with-recurrence"),
    "brake_verifying": seed_id("incident:brake-verifying"),
    "cooling_verified": seed_id("incident:cooling-verified"),
    "excavator_recurred": seed_id("incident:excavator-recurred"),
}
VERIFICATION_IDS = {
    "rule_no_event": seed_id("verification-rule:no-event"),
    "brake_pending": seed_id("verification-run:brake-pending"),
    "cooling_succeeded": seed_id("verification-run:cooling-succeeded"),
    "excavator_recurrence_detected": seed_id("verification-run:excavator-recurrence-detected"),
    "excavator_recurrence_evidence": seed_id("verification-evidence:excavator-recurrence"),
}
HANDOVER_IDS = {
    "historical_acknowledged": seed_id("handover:historical-acknowledged"),
    "current_unacknowledged": seed_id("handover:current-unacknowledged"),
}


@dataclass(frozen=True, slots=True)
class SeedSummary:
    seed_version: str
    anchor: str
    machines: dict[str, str]
    components: dict[str, str]
    incidents: dict[str, str]
    evidence: dict[str, str]
    handovers: dict[str, str]
    semantic_demo: dict[str, Any]
    validation: dict[str, Any]


class SeedError(RuntimeError):
    pass


def _context(*, shift: str, location: str, state: str, workload: str, environment: str) -> dict[str, Any]:
    return {
        "shift": {"value": shift, "quality": ContextQuality.KNOWN.value, "freshness_basis": "demo-shift-roster"},
        "location": {"value": location, "quality": ContextQuality.KNOWN.value, "freshness_basis": "demo-dispatch-location"},
        "machine_operating_state": {"value": state, "quality": ContextQuality.KNOWN.value, "freshness_basis": "demo-machine-state"},
        "workload": {"value": workload, "quality": ContextQuality.KNOWN.value, "freshness_basis": "demo-cycle-summary"},
        "environment": {"value": environment, "quality": ContextQuality.STALE.value, "freshness_basis": "demo-weather-sample-10m-prior"},
    }


def _evidence(
    *,
    key: str,
    machine_key: str,
    component_key: str | None,
    source_type: EvidenceSourceType,
    source_record_id: str,
    original_timestamp: datetime,
    canonical_event_type: str,
    payload: dict[str, Any],
    raw_payload: dict[str, Any],
    provenance: dict[str, Any],
) -> EvidenceEventRecord:
    return EvidenceEventRecord(
        id=EVIDENCE_IDS[key],
        machine_id=MACHINE_IDS[machine_key],
        component_id=COMPONENT_IDS[component_key] if component_key else None,
        source_type=source_type.value,
        original_source_record_id=source_record_id,
        original_timestamp=original_timestamp,
        ingestion_timestamp=original_timestamp + timedelta(minutes=1),
        canonical_event_type=canonical_event_type,
        canonical_payload=payload,
        raw_source_payload=raw_payload,
        provenance=provenance,
    )


def _audit(
    *, incident_key: str, action: IncidentAuditAction, at: datetime, suffix: str, payload: dict[str, Any]
) -> IncidentAuditEventRecord:
    return IncidentAuditEventRecord(
        id=seed_id(f"audit:{incident_key}:{suffix}"),
        incident_id=INCIDENT_IDS[incident_key],
        action=action,
        occurred_at=at,
        payload=payload,
    )


def _link(
    *,
    incident_key: str,
    evidence_key: str,
    relationship: IncidentEvidenceRelationshipType,
    at: datetime,
    suffix: str,
) -> IncidentEvidenceLinkRecord:
    return IncidentEvidenceLinkRecord(
        id=seed_id(f"link:{incident_key}:{suffix}"),
        incident_id=INCIDENT_IDS[incident_key],
        evidence_event_id=EVIDENCE_IDS[evidence_key],
        is_active=True,
        relationship_type=relationship,
        deterministic_rule_identifier="seed.demo.explicit.v1",
        link_reason=(
            "Deterministic demo association used to exercise the canonical "
            f"{relationship.value.lower()} path."
        ),
        linked_at=at,
        unlinked_at=None,
    )


def _parse_anchor(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SeedError(f"invalid --anchor timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise SeedError("--anchor must include a timezone offset or Z")
    return normalize_to_utc(parsed).replace(microsecond=0)


def _ensure_environment(settings: Settings) -> None:
    if settings.environment not in {"development", "test"}:
        raise SeedError(
            "demo seeding is disabled outside development/test environments; "
            f"current environment={settings.environment!r}"
        )


def _assert_schema(session: Session) -> None:
    try:
        session.execute(text("SELECT 1 FROM machines LIMIT 1"))
    except OperationalError as exc:
        raise SeedError(
            "database schema is not ready; run `alembic upgrade head` before seeding"
        ) from exc


def _reset_database(session: Session) -> None:
    # Explicit development reset uses Core DELETEs so immutable-history ORM guards
    # remain intact for normal application behavior.
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.flush()


def _seed_records(session: Session, settings: Settings, anchor: datetime) -> None:
    machines = [
        MachineRecord(
            id=MACHINE_IDS["haul_truck_01"],
            display_name="Haul Truck 01",
            asset_code="HT-01",
            machine_type="Haul Truck",
            manufacturer="Demo Manufacturer",
            model="Demo HT",
            site_name="North Mine",
            site_area="North Ramp",
        ),
        MachineRecord(
            id=MACHINE_IDS["excavator_01"],
            display_name="Excavator 01",
            asset_code="EX-01",
            machine_type="Excavator",
            manufacturer="Demo Manufacturer",
            model="Demo EX",
            site_name="North Mine",
            site_area="Pit 3",
        ),
        MachineRecord(
            id=MACHINE_IDS["loader_01"],
            display_name="Loader 01",
            asset_code="LD-01",
            machine_type="Wheel Loader",
            manufacturer="Demo Manufacturer",
            model="Demo WL",
            site_name="North Mine",
            site_area="Processing Yard",
        ),
    ]
    session.add_all(machines)
    session.flush()

    components = [
        ComponentRecord(
            id=COMPONENT_IDS["haul_hydraulics"],
            machine_id=MACHINE_IDS["haul_truck_01"],
            display_name="Main Hydraulics",
            component_type="Hydraulic System",
            manufacturer="Demo Manufacturer",
            model="HYD-HT",
        ),
        ComponentRecord(
            id=COMPONENT_IDS["haul_brakes"],
            machine_id=MACHINE_IDS["haul_truck_01"],
            display_name="Service Brakes",
            component_type="Brake System",
            manufacturer="Demo Manufacturer",
            model="BRK-HT",
        ),
        ComponentRecord(
            id=COMPONENT_IDS["excavator_hydraulics"],
            machine_id=MACHINE_IDS["excavator_01"],
            display_name="Main Hydraulics",
            component_type="Hydraulic System",
            manufacturer="Demo Manufacturer",
            model="HYD-EX",
        ),
        ComponentRecord(
            id=COMPONENT_IDS["loader_cooling"],
            machine_id=MACHINE_IDS["loader_01"],
            display_name="Engine Cooling",
            component_type="Cooling System",
            manufacturer="Demo Manufacturer",
            model="CLG-WL",
        ),
    ]
    session.add_all(components)
    session.flush()

    evidence = [
        _evidence(
            key="hydraulic_exact_history",
            machine_key="haul_truck_01",
            component_key="haul_hydraulics",
            source_type=EvidenceSourceType.MACHINE_EVENT,
            source_record_id="DEMO-ECU-HT01-HYD-0001",
            original_timestamp=anchor - timedelta(days=7),
            canonical_event_type="HYDRAULIC_PRESSURE_LOW",
            payload={"pressure_kpa": 18200, "threshold_kpa": 19000},
            raw_payload={"code": "HYD-P-LOW", "pressure": 18.2, "unit": "MPa"},
            provenance={"source_system": "demo-ecu", "channel": "hydraulic-pressure"},
        ),
        _evidence(
            key="hydraulic_semantic_history",
            machine_key="haul_truck_01",
            component_key="haul_hydraulics",
            source_type=EvidenceSourceType.HUMAN_OBSERVATION,
            source_record_id="DEMO-OBS-HT01-HYD-0001",
            original_timestamp=anchor - timedelta(days=6, hours=2),
            canonical_event_type="HYDRAULIC_RESPONSE_OBSERVATION",
            payload={
                "observation": "Boom response felt slow and the hydraulic pump sounded strained under load."
            },
            raw_payload={
                "note": "boom slower than usual; pump whining when loaded"
            },
            provenance={
                "source_system": "demo-operator-log",
                "observer_role": "operator",
                "semantic_demo": {
                    "label": "SIMILAR_SEMANTIC_HISTORY_CANDIDATE",
                    "candidate_for_evidence_id": str(EVIDENCE_IDS["hydraulic_initial"]),
                    "note": "Metadata only; Qdrant remains a derived optional index.",
                },
            },
        ),
        _evidence(
            key="hydraulic_initial",
            machine_key="haul_truck_01",
            component_key="haul_hydraulics",
            source_type=EvidenceSourceType.MACHINE_EVENT,
            source_record_id="DEMO-ECU-HT01-HYD-0100",
            original_timestamp=anchor - timedelta(minutes=30),
            canonical_event_type="HYDRAULIC_PRESSURE_LOW",
            payload={"pressure_kpa": 17850, "threshold_kpa": 19000},
            raw_payload={"fault": "HYD-P-LOW", "pressure": 17.85, "unit": "MPa"},
            provenance={"source_system": "demo-ecu", "firmware": "sim-1.0"},
        ),
        _evidence(
            key="hydraulic_recurrence",
            machine_key="haul_truck_01",
            component_key="haul_hydraulics",
            source_type=EvidenceSourceType.MACHINE_EVENT,
            source_record_id="DEMO-ECU-HT01-HYD-0101",
            original_timestamp=anchor - timedelta(minutes=20),
            canonical_event_type="HYDRAULIC_PRESSURE_LOW",
            payload={"pressure_kpa": 17620, "threshold_kpa": 19000},
            raw_payload={"fault": "HYD-P-LOW", "pressure": 17.62, "unit": "MPa"},
            provenance={"source_system": "demo-ecu", "firmware": "sim-1.0"},
        ),
        _evidence(
            key="maintenance_filter",
            machine_key="haul_truck_01",
            component_key="haul_hydraulics",
            source_type=EvidenceSourceType.MAINTENANCE_RECORD,
            source_record_id="DEMO-CMMS-HT01-0421",
            original_timestamp=anchor - timedelta(days=2),
            canonical_event_type="HYDRAULIC_FILTER_REPLACED",
            payload={"work_order": "WO-DEMO-0421", "action": "filter replaced"},
            raw_payload={"wo": "WO-DEMO-0421", "job": "replace return filter"},
            provenance={"source_system": "demo-cmms", "technician": "demo-tech-2"},
        ),
        _evidence(
            key="operator_audio",
            machine_key="haul_truck_01",
            component_key="haul_hydraulics",
            source_type=EvidenceSourceType.HUMAN_OBSERVATION,
            source_record_id="DEMO-OBS-HT01-HYD-AUDIO-01",
            original_timestamp=anchor - timedelta(minutes=27),
            canonical_event_type="HYDRAULIC_NOISE_OBSERVATION",
            payload={"observation": "Operator reported pump whine during loaded lift."},
            raw_payload={"note": "pump whine louder under load", "captured_as": "audio"},
            provenance={"source_system": "demo-operator-mobile", "observer_role": "operator"},
        ),
        _evidence(
            key="brake_exact_history",
            machine_key="haul_truck_01",
            component_key="haul_brakes",
            source_type=EvidenceSourceType.MACHINE_EVENT,
            source_record_id="DEMO-ECU-HT01-BRK-0001",
            original_timestamp=anchor - timedelta(days=5),
            canonical_event_type="BRAKE_TEMPERATURE_HIGH",
            payload={"temperature_c": 218, "threshold_c": 210},
            raw_payload={"code": "BRK-T-HIGH", "temp_c": 218},
            provenance={"source_system": "demo-ecu", "channel": "rear-left-brake-temp"},
        ),
        _evidence(
            key="brake_primary",
            machine_key="haul_truck_01",
            component_key="haul_brakes",
            source_type=EvidenceSourceType.MACHINE_EVENT,
            source_record_id="DEMO-ECU-HT01-BRK-0100",
            original_timestamp=anchor - timedelta(minutes=8),
            canonical_event_type="BRAKE_TEMPERATURE_HIGH",
            payload={"temperature_c": 226, "threshold_c": 210},
            raw_payload={"code": "BRK-T-HIGH", "temp_c": 226},
            provenance={"source_system": "demo-ecu", "channel": "rear-left-brake-temp"},
        ),
        _evidence(
            key="cooling_primary",
            machine_key="loader_01",
            component_key="loader_cooling",
            source_type=EvidenceSourceType.MACHINE_EVENT,
            source_record_id="DEMO-ECU-LD01-CLG-0100",
            original_timestamp=anchor - timedelta(hours=3),
            canonical_event_type="COOLANT_TEMPERATURE_HIGH",
            payload={"temperature_c": 109, "threshold_c": 105},
            raw_payload={"code": "CLG-T-HIGH", "temp_c": 109},
            provenance={"source_system": "demo-loader-ecu", "channel": "coolant-temp"},
        ),
        _evidence(
            key="excavator_initial",
            machine_key="excavator_01",
            component_key="excavator_hydraulics",
            source_type=EvidenceSourceType.MACHINE_EVENT,
            source_record_id="DEMO-ECU-EX01-HYD-0100",
            original_timestamp=anchor - timedelta(minutes=95),
            canonical_event_type="HYDRAULIC_PRESSURE_LOW",
            payload={"pressure_kpa": 16500, "threshold_kpa": 18000},
            raw_payload={"fault": "HYD-P-LOW", "pressure": 16.5, "unit": "MPa"},
            provenance={"source_system": "demo-excavator-ecu", "channel": "main-pressure"},
        ),
        _evidence(
            key="excavator_recurrence",
            machine_key="excavator_01",
            component_key="excavator_hydraulics",
            source_type=EvidenceSourceType.MACHINE_EVENT,
            source_record_id="DEMO-ECU-EX01-HYD-0101",
            original_timestamp=anchor - timedelta(minutes=70),
            canonical_event_type="HYDRAULIC_PRESSURE_LOW",
            payload={"pressure_kpa": 16150, "threshold_kpa": 18000},
            raw_payload={"fault": "HYD-P-LOW", "pressure": 16.15, "unit": "MPa"},
            provenance={"source_system": "demo-excavator-ecu", "channel": "main-pressure"},
        ),
    ]
    session.add_all(evidence)
    session.flush()

    # Historical evidence-time context. It is intentionally persisted separately
    # from current machine state and protected as immutable by the ORM model.
    for index, key in enumerate(EVIDENCE_IDS):
        record = next(item for item in evidence if item.id == EVIDENCE_IDS[key])
        session.add(
            ContextSnapshotRecord(
                id=seed_id(f"context:{key}"),
                evidence_event_id=record.id,
                quality=None,
                snapshot_payload=_context(
                    shift="SHIFT-A" if index % 2 == 0 else "SHIFT-B",
                    location="north-ramp" if record.machine_id == MACHINE_IDS["haul_truck_01"] else "pit-3",
                    state="LOADED" if index % 3 else "IDLE",
                    workload="HIGH" if index % 2 == 0 else "MEDIUM",
                    environment="dry / dusty",
                ),
            )
        )
    session.flush()

    session.add(
        EvidenceAttachmentRecord(
            id=seed_id("attachment:operator-audio"),
            evidence_event_id=EVIDENCE_IDS["operator_audio"],
            attachment_type="AUDIO",
            storage_reference="demo://attachments/ht01-hydraulic-whine.wav",
            mime_type="audio/wav",
            file_size=184_320,
            checksum="sha256:demo-5a7fb1a9c9b77d0f-not-a-production-file",
            created_at=anchor - timedelta(minutes=26),
        )
    )
    session.flush()

    incidents = [
        IncidentRecord(
            id=INCIDENT_IDS["hydraulic_open_with_recurrence"],
            machine_id=MACHINE_IDS["haul_truck_01"],
            status=IncidentStatus.OPEN,
            owner_ref="demo-maintenance-team-a",
            severity="HIGH",
            due_state="DUE_SOON",
            due_time=anchor + timedelta(hours=2),
            created_at=anchor - timedelta(minutes=29),
            updated_at=anchor - timedelta(minutes=19),
        ),
        IncidentRecord(
            id=INCIDENT_IDS["brake_verifying"],
            machine_id=MACHINE_IDS["haul_truck_01"],
            status=IncidentStatus.VERIFYING,
            owner_ref="demo-brake-specialist",
            severity="CRITICAL",
            due_state="IN_PROGRESS",
            due_time=anchor + timedelta(hours=1),
            created_at=anchor - timedelta(minutes=7),
            updated_at=anchor,
        ),
        IncidentRecord(
            id=INCIDENT_IDS["cooling_verified"],
            machine_id=MACHINE_IDS["loader_01"],
            status=IncidentStatus.VERIFIED,
            owner_ref="demo-loader-team",
            severity="MEDIUM",
            due_state="RESOLVED",
            due_time=anchor - timedelta(hours=1),
            created_at=anchor - timedelta(hours=3) + timedelta(minutes=1),
            updated_at=anchor - timedelta(hours=2),
        ),
        IncidentRecord(
            id=INCIDENT_IDS["excavator_recurred"],
            machine_id=MACHINE_IDS["excavator_01"],
            status=IncidentStatus.RECURRED,
            owner_ref="demo-hydraulic-team",
            severity="HIGH",
            due_state="ESCALATED",
            due_time=anchor + timedelta(minutes=45),
            created_at=anchor - timedelta(minutes=94),
            updated_at=anchor - timedelta(minutes=69),
        ),
    ]
    session.add_all(incidents)
    session.flush()

    links = [
        _link(
            incident_key="hydraulic_open_with_recurrence",
            evidence_key="hydraulic_initial",
            relationship=IncidentEvidenceRelationshipType.RELATED,
            at=anchor - timedelta(minutes=29),
            suffix="initial",
        ),
        _link(
            incident_key="hydraulic_open_with_recurrence",
            evidence_key="hydraulic_recurrence",
            relationship=IncidentEvidenceRelationshipType.RECURRENCE,
            at=anchor - timedelta(minutes=19),
            suffix="recurrence",
        ),
        _link(
            incident_key="brake_verifying",
            evidence_key="brake_primary",
            relationship=IncidentEvidenceRelationshipType.RELATED,
            at=anchor - timedelta(minutes=7),
            suffix="primary",
        ),
        _link(
            incident_key="cooling_verified",
            evidence_key="cooling_primary",
            relationship=IncidentEvidenceRelationshipType.RELATED,
            at=anchor - timedelta(hours=3) + timedelta(minutes=1),
            suffix="primary",
        ),
        _link(
            incident_key="excavator_recurred",
            evidence_key="excavator_initial",
            relationship=IncidentEvidenceRelationshipType.RELATED,
            at=anchor - timedelta(minutes=94),
            suffix="initial",
        ),
        _link(
            incident_key="excavator_recurred",
            evidence_key="excavator_recurrence",
            relationship=IncidentEvidenceRelationshipType.RECURRENCE,
            at=anchor - timedelta(minutes=69),
            suffix="recurrence",
        ),
    ]
    session.add_all(links)
    session.flush()

    rule = VerificationRuleRecord(
        id=VERIFICATION_IDS["rule_no_event"],
        identifier=settings.verification_rule_identifier,
        name=settings.verification_rule_name,
        rule_type=VerificationRuleType.NO_EVENT,
        window_minutes=settings.verification_window_minutes,
    )
    session.add(rule)
    session.flush()

    pending_start = anchor
    pending_end = pending_start + timedelta(minutes=settings.verification_window_minutes)
    verified_start = anchor - timedelta(
        minutes=settings.verification_window_minutes + 120
    )
    verified_end = verified_start + timedelta(minutes=settings.verification_window_minutes)
    recurrence_at = anchor - timedelta(minutes=70)
    recurred_start = recurrence_at - timedelta(seconds=30)
    recurred_end = recurred_start + timedelta(minutes=settings.verification_window_minutes)
    session.add_all(
        [
            VerificationRunRecord(
                id=VERIFICATION_IDS["brake_pending"],
                incident_id=INCIDENT_IDS["brake_verifying"],
                verification_rule_id=rule.id,
                result=None,
                started_at=pending_start,
                window_ends_at=pending_end,
                completed_at=None,
            ),
            VerificationRunRecord(
                id=VERIFICATION_IDS["cooling_succeeded"],
                incident_id=INCIDENT_IDS["cooling_verified"],
                verification_rule_id=rule.id,
                result=VerificationRunResult.SUCCEEDED,
                started_at=verified_start,
                window_ends_at=verified_end,
                completed_at=verified_end,
            ),
            VerificationRunRecord(
                id=VERIFICATION_IDS["excavator_recurrence_detected"],
                incident_id=INCIDENT_IDS["excavator_recurred"],
                verification_rule_id=rule.id,
                result=VerificationRunResult.RECURRENCE_DETECTED,
                started_at=recurred_start,
                window_ends_at=recurred_end,
                completed_at=recurrence_at + timedelta(minutes=1),
            ),
        ]
    )
    session.flush()
    session.add(
        VerificationEvidenceRecord(
            id=VERIFICATION_IDS["excavator_recurrence_evidence"],
            verification_run_id=VERIFICATION_IDS["excavator_recurrence_detected"],
            evidence_event_id=EVIDENCE_IDS["excavator_recurrence"],
        )
    )
    session.flush()

    audits = [
        _audit(
            incident_key="hydraulic_open_with_recurrence",
            action=IncidentAuditAction.INCIDENT_CREATED,
            at=anchor - timedelta(minutes=29),
            suffix="created",
            payload={"seed": True},
        ),
        _audit(
            incident_key="hydraulic_open_with_recurrence",
            action=IncidentAuditAction.EVIDENCE_LINKED,
            at=anchor - timedelta(minutes=29),
            suffix="initial-linked",
            payload={"evidence_event_id": str(EVIDENCE_IDS["hydraulic_initial"])},
        ),
        _audit(
            incident_key="hydraulic_open_with_recurrence",
            action=IncidentAuditAction.EVIDENCE_LINKED,
            at=anchor - timedelta(minutes=19),
            suffix="recurrence-linked",
            payload={"evidence_event_id": str(EVIDENCE_IDS["hydraulic_recurrence"])},
        ),
        _audit(
            incident_key="hydraulic_open_with_recurrence",
            action=IncidentAuditAction.RECURRENCE_RECORDED,
            at=anchor - timedelta(minutes=19),
            suffix="recurrence-recorded",
            payload={"evidence_event_id": str(EVIDENCE_IDS["hydraulic_recurrence"])},
        ),
        _audit(
            incident_key="brake_verifying",
            action=IncidentAuditAction.INCIDENT_CREATED,
            at=anchor - timedelta(minutes=7),
            suffix="created",
            payload={"seed": True},
        ),
        _audit(
            incident_key="brake_verifying",
            action=IncidentAuditAction.EVIDENCE_LINKED,
            at=anchor - timedelta(minutes=7),
            suffix="primary-linked",
            payload={"evidence_event_id": str(EVIDENCE_IDS["brake_primary"])},
        ),
        _audit(
            incident_key="brake_verifying",
            action=IncidentAuditAction.STATUS_CHANGED,
            at=pending_start,
            suffix="verifying",
            payload={"from_status": "OPEN", "to_status": "VERIFYING", "verification_run_id": str(VERIFICATION_IDS["brake_pending"])},
        ),
        _audit(
            incident_key="cooling_verified",
            action=IncidentAuditAction.INCIDENT_CREATED,
            at=anchor - timedelta(hours=3) + timedelta(minutes=1),
            suffix="created",
            payload={"seed": True},
        ),
        _audit(
            incident_key="cooling_verified",
            action=IncidentAuditAction.EVIDENCE_LINKED,
            at=anchor - timedelta(hours=3) + timedelta(minutes=1),
            suffix="primary-linked",
            payload={"evidence_event_id": str(EVIDENCE_IDS["cooling_primary"])},
        ),
        _audit(
            incident_key="cooling_verified",
            action=IncidentAuditAction.STATUS_CHANGED,
            at=verified_start,
            suffix="verifying",
            payload={"from_status": "OPEN", "to_status": "VERIFYING", "verification_run_id": str(VERIFICATION_IDS["cooling_succeeded"])},
        ),
        _audit(
            incident_key="cooling_verified",
            action=IncidentAuditAction.STATUS_CHANGED,
            at=verified_end,
            suffix="verified",
            payload={"from_status": "VERIFYING", "to_status": "VERIFIED", "verification_run_id": str(VERIFICATION_IDS["cooling_succeeded"])},
        ),
        _audit(
            incident_key="excavator_recurred",
            action=IncidentAuditAction.INCIDENT_CREATED,
            at=anchor - timedelta(minutes=94),
            suffix="created",
            payload={"seed": True},
        ),
        _audit(
            incident_key="excavator_recurred",
            action=IncidentAuditAction.EVIDENCE_LINKED,
            at=anchor - timedelta(minutes=94),
            suffix="initial-linked",
            payload={"evidence_event_id": str(EVIDENCE_IDS["excavator_initial"])},
        ),
        _audit(
            incident_key="excavator_recurred",
            action=IncidentAuditAction.STATUS_CHANGED,
            at=recurred_start,
            suffix="verifying",
            payload={"from_status": "OPEN", "to_status": "VERIFYING", "verification_run_id": str(VERIFICATION_IDS["excavator_recurrence_detected"])},
        ),
        _audit(
            incident_key="excavator_recurred",
            action=IncidentAuditAction.EVIDENCE_LINKED,
            at=recurrence_at + timedelta(minutes=1),
            suffix="recurrence-linked",
            payload={"evidence_event_id": str(EVIDENCE_IDS["excavator_recurrence"])},
        ),
        _audit(
            incident_key="excavator_recurred",
            action=IncidentAuditAction.STATUS_CHANGED,
            at=recurrence_at + timedelta(minutes=1),
            suffix="recurred",
            payload={"from_status": "VERIFYING", "to_status": "RECURRED", "evidence_event_id": str(EVIDENCE_IDS["excavator_recurrence"])},
        ),
        _audit(
            incident_key="excavator_recurred",
            action=IncidentAuditAction.RECURRENCE_RECORDED,
            at=recurrence_at + timedelta(minutes=1),
            suffix="recurrence-recorded",
            payload={"evidence_event_id": str(EVIDENCE_IDS["excavator_recurrence"])},
        ),
    ]
    session.add_all(audits)
    session.flush()

    historical_handover_created = recurrence_at - timedelta(seconds=15)
    historical_handover_acknowledged = recurrence_at - timedelta(seconds=10)
    historical_packet = HandoverPacketRecord(
        id=HANDOVER_IDS["historical_acknowledged"],
        created_at=historical_handover_created,
        acknowledged_at=historical_handover_acknowledged,
    )
    current_packet = HandoverPacketRecord(
        id=HANDOVER_IDS["current_unacknowledged"],
        created_at=anchor,
        acknowledged_at=None,
    )
    session.add_all([historical_packet, current_packet])
    session.flush()

    # Historical packet deliberately captures the excavator as VERIFYING; its
    # authoritative incident later becomes RECURRED. This demonstrates snapshot
    # immutability without rewriting the handover history.
    session.add_all(
        [
            HandoverItemRecord(
                id=seed_id("handover-item:historical:hydraulic-open"),
                handover_packet_id=historical_packet.id,
                incident_id=INCIDENT_IDS["hydraulic_open_with_recurrence"],
                severity_snapshot="HIGH",
                owner_ref_snapshot="demo-maintenance-team-a",
                status_snapshot=IncidentStatus.OPEN,
                due_state_snapshot="DUE_SOON",
                due_time_snapshot=anchor + timedelta(hours=2),
            ),
            HandoverItemRecord(
                id=seed_id("handover-item:historical:excavator-verifying"),
                handover_packet_id=historical_packet.id,
                incident_id=INCIDENT_IDS["excavator_recurred"],
                severity_snapshot="HIGH",
                owner_ref_snapshot="demo-hydraulic-team",
                status_snapshot=IncidentStatus.VERIFYING,
                due_state_snapshot="IN_PROGRESS",
                due_time_snapshot=anchor + timedelta(minutes=45),
            ),
            HandoverItemRecord(
                id=seed_id("handover-item:current:hydraulic-open"),
                handover_packet_id=current_packet.id,
                incident_id=INCIDENT_IDS["hydraulic_open_with_recurrence"],
                severity_snapshot="HIGH",
                owner_ref_snapshot="demo-maintenance-team-a",
                status_snapshot=IncidentStatus.OPEN,
                due_state_snapshot="DUE_SOON",
                due_time_snapshot=anchor + timedelta(hours=2),
            ),
            HandoverItemRecord(
                id=seed_id("handover-item:current:brake-verifying"),
                handover_packet_id=current_packet.id,
                incident_id=INCIDENT_IDS["brake_verifying"],
                severity_snapshot="CRITICAL",
                owner_ref_snapshot="demo-brake-specialist",
                status_snapshot=IncidentStatus.VERIFYING,
                due_state_snapshot="IN_PROGRESS",
                due_time_snapshot=anchor + timedelta(hours=1),
            ),
            HandoverItemRecord(
                id=seed_id("handover-item:current:excavator-recurred"),
                handover_packet_id=current_packet.id,
                incident_id=INCIDENT_IDS["excavator_recurred"],
                severity_snapshot="HIGH",
                owner_ref_snapshot="demo-hydraulic-team",
                status_snapshot=IncidentStatus.RECURRED,
                due_state_snapshot="ESCALATED",
                due_time_snapshot=anchor + timedelta(minutes=45),
            ),
        ]
    )
    session.flush()

    for incident_key in ("hydraulic_open_with_recurrence", "excavator_recurred"):
        session.add(
            _audit(
                incident_key=incident_key,
                action=IncidentAuditAction.HANDOVER_ACKNOWLEDGED,
                at=historical_handover_acknowledged,
                suffix="historical-handover-ack",
                payload={"handover_packet_id": str(historical_packet.id)},
            )
        )
    session.flush()


def _validate(session: Session, settings: Settings, anchor: datetime) -> dict[str, Any]:
    foreign_key_issues = session.execute(text("PRAGMA foreign_key_check")).all()
    if foreign_key_issues:
        raise SeedError(f"foreign-key validation failed: {foreign_key_issues!r}")

    expected_machine_ids = set(MACHINE_IDS.values())
    existing_machine_ids = set(session.scalars(select(MachineRecord.id)).all())
    if not expected_machine_ids.issubset(existing_machine_ids):
        raise SeedError("one or more deterministic seed machines are missing")

    expected_evidence_ids = set(EVIDENCE_IDS.values())
    existing_evidence_ids = set(session.scalars(select(EvidenceEventRecord.id)).all())
    if not expected_evidence_ids.issubset(existing_evidence_ids):
        raise SeedError("one or more deterministic seed evidence rows are missing")

    duplicate_source_identities = session.execute(
        select(
            EvidenceEventRecord.source_type,
            EvidenceEventRecord.original_source_record_id,
            func.count(EvidenceEventRecord.id),
        )
        .group_by(EvidenceEventRecord.source_type, EvidenceEventRecord.original_source_record_id)
        .having(func.count(EvidenceEventRecord.id) > 1)
    ).all()
    if duplicate_source_identities:
        raise SeedError(f"duplicate source identities detected: {duplicate_source_identities!r}")

    inconsistent_links = session.scalars(
        select(IncidentEvidenceLinkRecord).where(
            ((IncidentEvidenceLinkRecord.is_active.is_(True)) & (IncidentEvidenceLinkRecord.unlinked_at.is_not(None)))
            | ((IncidentEvidenceLinkRecord.is_active.is_(False)) & (IncidentEvidenceLinkRecord.unlinked_at.is_(None)))
        )
    ).all()
    if inconsistent_links:
        raise SeedError("incident evidence link active/unlinked invariants failed")

    recurrence_count = session.scalar(
        select(func.count(IncidentEvidenceLinkRecord.id)).where(
            IncidentEvidenceLinkRecord.incident_id == INCIDENT_IDS["hydraulic_open_with_recurrence"],
            IncidentEvidenceLinkRecord.is_active.is_(True),
            IncidentEvidenceLinkRecord.relationship_type.in_(
                [IncidentEvidenceRelationshipType.RELATED, IncidentEvidenceRelationshipType.RECURRENCE]
            ),
        )
    )
    if recurrence_count != 2:
        raise SeedError("hydraulic demo incident must reconstruct exactly two occurrences")

    pending = session.get(VerificationRunRecord, VERIFICATION_IDS["brake_pending"])
    if pending is None or pending.completed_at is not None or pending.result is not None:
        raise SeedError("pending verification scenario is invalid")
    if pending.window_ends_at is None or pending.window_ends_at <= pending.started_at:
        raise SeedError("pending verification window is invalid")

    verified = session.get(VerificationRunRecord, VERIFICATION_IDS["cooling_succeeded"])
    if verified is None or verified.result != VerificationRunResult.SUCCEEDED or verified.completed_at is None:
        raise SeedError("verified incident scenario is invalid")

    recurred = session.get(VerificationRunRecord, VERIFICATION_IDS["excavator_recurrence_detected"])
    if recurred is None or recurred.result != VerificationRunResult.RECURRENCE_DETECTED:
        raise SeedError("recurred incident verification scenario is invalid")
    verification_evidence = session.scalar(
        select(func.count(VerificationEvidenceRecord.id)).where(
            VerificationEvidenceRecord.verification_run_id == recurred.id,
            VerificationEvidenceRecord.evidence_event_id == EVIDENCE_IDS["excavator_recurrence"],
        )
    )
    if verification_evidence != 1:
        raise SeedError("recurred verification evidence is missing")

    historical_item = session.get(HandoverItemRecord, seed_id("handover-item:historical:excavator-verifying"))
    final_recurred_incident = session.get(IncidentRecord, INCIDENT_IDS["excavator_recurred"])
    if historical_item is None or historical_item.status_snapshot != IncidentStatus.VERIFYING:
        raise SeedError("historical handover snapshot was not preserved")
    if final_recurred_incident is None or final_recurred_incident.status != IncidentStatus.RECURRED:
        raise SeedError("recurred incident final state is invalid")

    exact_history = session.get(EvidenceEventRecord, EVIDENCE_IDS["hydraulic_exact_history"])
    primary = session.get(EvidenceEventRecord, EVIDENCE_IDS["hydraulic_initial"])
    if (
        exact_history is None
        or primary is None
        or exact_history.machine_id != primary.machine_id
        or exact_history.component_id != primary.component_id
        or exact_history.canonical_event_type != primary.canonical_event_type
        or exact_history.original_timestamp >= primary.original_timestamp
    ):
        raise SeedError("exact historical evidence scenario is invalid")

    semantic_candidate = session.get(EvidenceEventRecord, EVIDENCE_IDS["hydraulic_semantic_history"])
    if semantic_candidate is None or "semantic_demo" not in semantic_candidate.provenance:
        raise SeedError("semantic historical evidence metadata is missing")

    attachment = session.scalar(
        select(EvidenceAttachmentRecord).where(
            EvidenceAttachmentRecord.evidence_event_id == EVIDENCE_IDS["operator_audio"]
        )
    )
    if attachment is None or attachment.attachment_type != "AUDIO" or not attachment.checksum:
        raise SeedError("audio attachment metadata scenario is invalid")

    return {
        "foreign_keys": "ok",
        "source_identity_uniqueness": "ok",
        "active_link_invariants": "ok",
        "occurrence_reconstruction": {"incident_id": str(INCIDENT_IDS["hydraulic_open_with_recurrence"]), "count": int(recurrence_count)},
        "verification_windows": "ok",
        "handover_snapshot_immutability": "ok",
        "exact_history": "ok",
        "semantic_candidate_metadata": "ok",
        "audio_attachment_metadata": "ok",
        "verification_window_minutes": settings.verification_window_minutes,
        "validated_at_anchor": anchor.isoformat(),
    }


def _build_summary(session: Session, anchor: datetime, validation: dict[str, Any]) -> SeedSummary:
    return SeedSummary(
        seed_version=SEED_VERSION,
        anchor=anchor.isoformat(),
        machines={key: str(value) for key, value in MACHINE_IDS.items()},
        components={key: str(value) for key, value in COMPONENT_IDS.items()},
        incidents={key: str(value) for key, value in INCIDENT_IDS.items()},
        evidence={key: str(value) for key, value in EVIDENCE_IDS.items()},
        handovers={key: str(value) for key, value in HANDOVER_IDS.items()},
        semantic_demo={
            "query_evidence_id": str(EVIDENCE_IDS["hydraulic_initial"]),
            "candidate_evidence_id": str(EVIDENCE_IDS["hydraulic_semantic_history"]),
            "candidate_label": "SIMILAR_SEMANTIC_HISTORY_CANDIDATE",
            "note": (
                "The SQLite row is canonical demo evidence and carries only metadata "
                "identifying an intended semantic pair. Populate the optional Qdrant "
                "index through the configured embedding/index integration to exercise "
                "live semantic search; SQLite never stores a similarity score."
            ),
        },
        validation=validation,
    )


def seed_database(
    settings: Settings,
    *,
    reset: bool = False,
    anchor: datetime | None = None,
) -> SeedSummary:
    _ensure_environment(settings)
    seed_anchor = normalize_to_utc(anchor or datetime.now(timezone.utc)).replace(microsecond=0)
    engine = create_database_engine(settings)
    SessionMaker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    try:
        with SessionMaker() as probe_session:
            _assert_schema(probe_session)
            existing_seed_machine = probe_session.get(
                MachineRecord, MACHINE_IDS["haul_truck_01"]
            )
            existing = existing_seed_machine is not None
            any_domain_data = bool(
                probe_session.scalar(select(func.count(MachineRecord.id)))
                or probe_session.scalar(select(func.count(EvidenceEventRecord.id)))
                or probe_session.scalar(select(func.count(IncidentRecord.id)))
            )

        if not reset and not existing and any_domain_data:
            raise SeedError(
                "database already contains non-seed domain data; use a dedicated "
                "development database or explicitly run `python -m app.seed --reset`"
            )

        if reset:
            with SessionMaker.begin() as write_session:
                _reset_database(write_session)
                _seed_records(write_session, settings, seed_anchor)
            with SessionMaker() as validation_session:
                validation = _validate(validation_session, settings, seed_anchor)
                return _build_summary(validation_session, seed_anchor, validation)

        if existing:
            # A second invocation is idempotent: validate and report the already
            # persisted seed rather than duplicating any canonical evidence.
            with SessionMaker() as existing_session:
                first_event = existing_session.get(
                    EvidenceEventRecord, EVIDENCE_IDS["hydraulic_initial"]
                )
                if first_event is None:
                    raise SeedError(
                        "partial demo seed detected; use `python -m app.seed --reset` "
                        "to rebuild the local development database"
                    )
                persisted_anchor = (
                    normalize_to_utc(first_event.original_timestamp)
                    + timedelta(minutes=30)
                )
                validation = _validate(existing_session, settings, persisted_anchor)
                return _build_summary(existing_session, persisted_anchor, validation)

        with SessionMaker.begin() as write_session:
            _seed_records(write_session, settings, seed_anchor)
        with SessionMaker() as validation_session:
            validation = _validate(validation_session, settings, seed_anchor)
            return _build_summary(validation_session, seed_anchor, validation)
    finally:
        engine.dispose()

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed the MINE-TRACE development/demo database")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="clear all domain data in the configured development/test database before reseeding",
    )
    parser.add_argument(
        "--anchor",
        default=None,
        help="timezone-aware ISO-8601 anchor; omit to anchor the active demo scenario to current UTC",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        summary = seed_database(
            get_settings(),
            reset=bool(args.reset),
            anchor=_parse_anchor(args.anchor),
        )
    except SeedError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
        return 2

    print(json.dumps({"status": "ok", "seed": asdict(summary)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
