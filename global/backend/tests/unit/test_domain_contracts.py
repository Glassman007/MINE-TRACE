from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain import (
    ContextDimension,
    ContextQuality,
    ContextSnapshot,
    EvidenceBundle,
    EvidenceBundleStatus,
    Incident,
    IncidentAuditAction,
    IncidentAuditEvent,
    IncidentEvidenceLink,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
    InvalidIncidentTransition,
    validate_incident_transition,
)


def test_enum_serialization_uses_canonical_values() -> None:
    incident = Incident(id=uuid4(), machine_id=uuid4(), status=IncidentStatus.OPEN)
    link = IncidentEvidenceLink(
        id=uuid4(),
        incident_id=incident.id,
        evidence_event_id=uuid4(),
        relationship_type=IncidentEvidenceRelationshipType.RECURRENCE,
    )
    audit = IncidentAuditEvent(
        id=uuid4(),
        incident_id=incident.id,
        action=IncidentAuditAction.STATUS_CHANGED,
        occurred_at=datetime.now(timezone.utc),
    )

    assert incident.model_dump(mode="json")["status"] == "OPEN"
    assert link.model_dump(mode="json")["relationship_type"] == "RECURRENCE"
    assert audit.model_dump(mode="json")["action"] == "STATUS_CHANGED"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (IncidentStatus.OPEN, IncidentStatus.VERIFYING),
        (IncidentStatus.VERIFYING, IncidentStatus.VERIFIED),
        (IncidentStatus.VERIFYING, IncidentStatus.RECURRED),
        (IncidentStatus.VERIFIED, IncidentStatus.RECURRED),
        (IncidentStatus.RECURRED, IncidentStatus.VERIFYING),
    ],
)
def test_required_lifecycle_transitions_are_allowed(
    current: IncidentStatus,
    target: IncidentStatus,
) -> None:
    validate_incident_transition(current, target)


def test_open_to_verified_is_rejected() -> None:
    with pytest.raises(
        InvalidIncidentTransition,
        match="OPEN -> VERIFIED",
    ):
        validate_incident_transition(IncidentStatus.OPEN, IncidentStatus.VERIFIED)


def test_invalid_context_quality_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ContextDimension(
            value="A",
            quality="FRESH",
            freshness_basis="shift-roster",
        )


def test_invalid_evidence_bundle_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceBundle(
            incident_id=uuid4(),
            status="COMPLETE",
        )


def test_context_and_bundle_statuses_serialize_canonically() -> None:
    stale_dimension = ContextDimension(
        value=0.8,
        quality=ContextQuality.STALE,
        freshness_basis="last-load-sample",
    )
    unknown_dimension = ContextDimension(
        value=None,
        quality=ContextQuality.UNKNOWN,
        freshness_basis="not-reported",
    )
    known_dimension = ContextDimension(
        value="A",
        quality=ContextQuality.KNOWN,
        freshness_basis="shift-roster",
    )
    context = ContextSnapshot(
        id=uuid4(),
        evidence_event_id=uuid4(),
        shift=known_dimension,
        location=known_dimension,
        machine_operating_state=known_dimension,
        workload=stale_dimension,
        environment=unknown_dimension,
    )
    bundle = EvidenceBundle(
        incident_id=uuid4(),
        status=EvidenceBundleStatus.INSUFFICIENT_EVIDENCE,
    )

    assert context.model_dump(mode="json")["workload"]["quality"] == "STALE"
    assert (
        bundle.model_dump(mode="json")["status"]
        == "INSUFFICIENT_EVIDENCE"
    )


def test_all_required_audit_actions_are_representable() -> None:
    assert {action.value for action in IncidentAuditAction} == {
        "INCIDENT_CREATED",
        "EVIDENCE_LINKED",
        "EVIDENCE_UNLINKED",
        "INCIDENT_SPLIT",
        "STATUS_CHANGED",
        "OWNER_CHANGED",
        "SEVERITY_CHANGED",
        "DUE_STATE_CHANGED",
        "DUE_TIME_CHANGED",
        "RECURRENCE_RECORDED",
        "HANDOVER_ACKNOWLEDGED",
    }
