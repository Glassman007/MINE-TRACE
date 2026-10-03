from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.contracts.sync import SyncEnvelope, parse_sync_envelope, with_computed_checksum

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
ZERO_CHECKSUM = "sha256:" + "0" * 64


def envelope_payload(
    *,
    machine_id: UUID | None = None,
    session_id: UUID | None = None,
    package_id: UUID | None = None,
    report_id: UUID | None = None,
    report_revision: int = 1,
    component_id: UUID | None = None,
    incident_id: UUID | None = None,
    evidence_id: UUID | None = None,
    action_id: UUID | None = None,
    verification_id: UUID | None = None,
) -> dict:
    machine_id = machine_id or uuid4()
    session_id = session_id or uuid4()
    package_id = package_id or uuid4()
    report_id = report_id or uuid4()
    component_id = component_id or uuid4()
    incident_id = incident_id or uuid4()
    evidence_id = evidence_id or uuid4()
    action_id = action_id or uuid4()
    verification_id = verification_id or uuid4()
    return {
        "schema_version": "1.0.0",
        "package_id": str(package_id),
        "source_machine_id": str(machine_id),
        "session_id": str(session_id),
        "report_revision": report_revision,
        "machine_session_report": {
            "schema_version": "1.0.0",
            "report_id": str(report_id),
            "report_revision": report_revision,
            "generated_at": NOW.isoformat(),
            "machine": {
                "machine_id": str(machine_id),
                "asset_code": f"asset-{str(machine_id)[:8]}",
                "display_name": "Haul Truck",
                "machine_type": "HAUL_TRUCK",
                "model": "MT-100",
                "site_name": "North Pit",
            },
            "session": {
                "session_id": str(session_id),
                "machine_id": str(machine_id),
                "started_at": NOW.isoformat(),
                "ended_at": NOW.replace(hour=17).isoformat(),
                "state": "CLOSED",
                "operating_hours": str(Decimal("8.0")),
            },
            "components": [
                {
                    "component_id": str(component_id),
                    "machine_id": str(machine_id),
                    "display_name": "Hydraulic pump",
                    "component_type": "HYDRAULIC_PUMP",
                }
            ],
            "maintenance_actions": [
                {
                    "action_id": str(action_id),
                    "machine_id": str(machine_id),
                    "incident_id": str(incident_id),
                    "session_id": str(session_id),
                    "component_id": str(component_id),
                    "action_type": "INSPECTION",
                    "description": "Inspected pump housing",
                    "original_timestamp": NOW.replace(hour=14).isoformat(),
                    "provenance": {"source": "edge-maintenance"},
                }
            ],
            "verification_runs": [
                {
                    "verification_run_id": str(verification_id),
                    "incident_id": str(incident_id),
                    "session_id": str(session_id),
                    "source_machine_id": str(machine_id),
                    "rule_identifier": "edge.no-event.v1",
                    "result": "SUCCEEDED",
                    "started_at": NOW.replace(hour=15).isoformat(),
                    "completed_at": NOW.replace(hour=16).isoformat(),
                    "original_timestamp": NOW.replace(hour=15).isoformat(),
                    "outcome_payload": {"source": "edge"},
                    "evidence_ids": [str(evidence_id)],
                }
            ],
        },
        "incident_updates": [
            {
                "incident_id": str(incident_id),
                "machine_id": str(machine_id),
                "session_id": str(session_id),
                "component_id": str(component_id),
                "status": "VERIFIED",
                "first_seen_at": NOW.replace(hour=10).isoformat(),
                "last_seen_at": NOW.replace(hour=13).isoformat(),
                "evidence_links": [
                    {
                        "evidence_id": str(evidence_id),
                        "relationship_type": "RELATED",
                        "link_reason": "edge supplied relationship",
                    }
                ],
            }
        ],
        "evidence_manifest": {
            "schema_version": "1.0.0",
            "source_machine_id": str(machine_id),
            "session_id": str(session_id),
            "entries": [
                {
                    "evidence_id": str(evidence_id),
                    "source_machine_id": str(machine_id),
                    "session_id": str(session_id),
                    "component_id": str(component_id),
                    "incident_ids": [str(incident_id)],
                    "source_type": "HUMAN_OBSERVATION",
                    "original_source_record_id": f"obs-{evidence_id}",
                    "original_timestamp": NOW.replace(hour=11).isoformat(),
                    "canonical_event_type": "OPERATOR_NOTE",
                    "canonical_payload": {"text": "hydraulic whine observed"},
                    "provenance": {"edge": "operator-console"},
                }
            ],
        },
        "important_text_evidence": [
            {
                "evidence_id": str(evidence_id),
                "semantic_kind": "operator_observation",
                "text": "hydraulic whine observed",
            }
        ],
        "optional_policy_selected_raw_evidence": [],
        "sync_metadata": {
            "checksum_algorithm": "sha256",
            "checksum": ZERO_CHECKSUM,
            "produced_at": NOW.replace(hour=17, minute=1).isoformat(),
            "producer_version": "edge-test-1",
        },
    }


def signed_envelope(**kwargs) -> SyncEnvelope:
    payload = envelope_payload(**kwargs)
    unsigned = parse_sync_envelope(payload)
    return with_computed_checksum(unsigned)


def signed_payload(**kwargs) -> dict:
    return signed_envelope(**kwargs).model_dump(mode="json")


def clone_payload(payload: dict) -> dict:
    return deepcopy(payload)
