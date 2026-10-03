from __future__ import annotations

import inspect
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.domain.enums import (
    EvidenceBundleSourceClassification,
    EvidenceBundleStatus,
    IncidentEvidenceRelationshipType,
    VerificationRuleType,
    VerificationRunResult,
)
from app.schemas.ai_provider import AIAnalysisStatus, AIClaimType
from app.schemas.ai_validation import (
    AIValidationFailureCode,
    AIValidationStage,
    AIValidationStatus,
)
from app.schemas.evidence_bundle import (
    BundleEvidenceItem,
    EvidenceBundleCompleteness,
    EvidenceBundleResponse,
    ProvenanceIndexItem,
    SemanticRetrievalMetadata,
    VerificationContextItem,
)
from app.services.ai_validation import AIValidationGuard


INCIDENT_ID = UUID("10000000-0000-0000-0000-000000000001")
MACHINE_ID = UUID("20000000-0000-0000-0000-000000000001")
EVIDENCE_ID = UUID("30000000-0000-0000-0000-000000000001")
OUTSIDE_BUNDLE_ID = UUID("99999999-0000-0000-0000-000000000999")
NOW = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)


def _bundle(
    *,
    verification_result: VerificationRunResult | None = None,
    relationship_type: IncidentEvidenceRelationshipType = IncidentEvidenceRelationshipType.RELATED,
) -> EvidenceBundleResponse:
    item = BundleEvidenceItem(
        evidence_id=EVIDENCE_ID,
        machine_id=MACHINE_ID,
        component_id=None,
        source_type="HUMAN_OBSERVATION",
        original_source_record_id="obs-1",
        original_timestamp=NOW,
        ingestion_timestamp=NOW,
        canonical_event_type="OPERATOR_OBSERVATION",
        canonical_payload={"note": "Hydraulic whine observed under load."},
        raw_source_payload={"note": "Hydraulic whine observed under load."},
        provenance={"source_system": "operator_log"},
        source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
        inclusion_reason="linked to incident",
        relationship_type=relationship_type,
        deterministic_rule_identifier="test.rule",
        similarity_score=None,
        anchor_evidence_id=None,
    )
    provenance = ProvenanceIndexItem(
        evidence_id=EVIDENCE_ID,
        source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
        source_type="HUMAN_OBSERVATION",
        original_source_record_id="obs-1",
        provenance={"source_system": "operator_log"},
    )
    verification_context = []
    if verification_result is not None:
        verification_context = [
            VerificationContextItem(
                verification_run_id=UUID("40000000-0000-0000-0000-000000000001"),
                verification_rule_id=UUID("50000000-0000-0000-0000-000000000001"),
                rule_identifier="no-recurrence-window",
                rule_name="No recurrence window",
                rule_type=VerificationRuleType.NO_EVENT,
                window_minutes=30,
                result=verification_result,
                started_at=NOW,
                window_ends_at=NOW,
                completed_at=NOW,
                evidence_ids=[EVIDENCE_ID],
            )
        ]
    return EvidenceBundleResponse(
        incident_id=INCIDENT_ID,
        status=EvidenceBundleStatus.READY,
        primary_incident_evidence=[item],
        selected_exact_history=[],
        selected_semantic_history=[],
        verification_context=verification_context,
        evidence_time_context_snapshots=[],
        provenance_index=[provenance],
        completeness=EvidenceBundleCompleteness(
            canonical_readiness_policy="test",
            status_reason="ready",
            incomplete_sections=[],
            truncated_sections=[],
            semantic_retrieval=SemanticRetrievalMetadata(
                configured=False,
                attempted=False,
                failed=False,
                failures=[],
                queried_primary_evidence_ids=[],
            ),
        ),
    )


def _candidate(
    *,
    claim_type: str = "OBSERVATION_RECORDED",
    text: str = "Hydraulic whine was recorded under load.",
    evidence_id: str | UUID = EVIDENCE_ID,
    summary: str = "The bundle records an operator observation.",
) -> dict[str, object]:
    return {
        "status": AIAnalysisStatus.UNVALIDATED.value,
        "summary": summary,
        "claims": [
            {
                "claim_type": claim_type,
                "text": text,
                "evidence_ids": [str(evidence_id)],
            }
        ],
        "limitations": ["The bundle does not establish a root cause."],
    }


def _reject(candidate: object, bundle: EvidenceBundleResponse | None = None):
    result = AIValidationGuard().validate(candidate, bundle or _bundle())
    assert result.status is AIValidationStatus.REJECTED
    assert result.analysis is None
    assert result.failure is not None
    return result.failure


def test_valid_structured_candidate_is_validated() -> None:
    result = AIValidationGuard().validate(_candidate(), _bundle())

    assert result.status is AIValidationStatus.VALIDATED
    assert result.failure is None
    assert result.analysis is not None
    assert result.analysis.claims[0].claim_type is AIClaimType.OBSERVATION_RECORDED


def test_schema_validation_runs_first() -> None:
    candidate = _candidate(text="The proven root cause is pump cavitation.")
    candidate["status"] = "VALIDATED"

    failure = _reject(candidate)

    assert failure.stage is AIValidationStage.SCHEMA_VALIDATION
    assert failure.code is AIValidationFailureCode.INVALID_SCHEMA


def test_malformed_evidence_id_is_schema_failure() -> None:
    failure = _reject(_candidate(evidence_id="not-a-uuid"))

    assert failure.stage is AIValidationStage.SCHEMA_VALIDATION
    assert failure.code is AIValidationFailureCode.MALFORMED_EVIDENCE_ID


def test_model_confidence_field_is_not_trusted_or_accepted() -> None:
    candidate = _candidate()
    candidate["confidence"] = 0.99

    failure = _reject(candidate)

    assert failure.stage is AIValidationStage.SCHEMA_VALIDATION
    assert failure.code is AIValidationFailureCode.INVALID_SCHEMA


def test_invented_citation_is_rejected() -> None:
    failure = _reject(_candidate(evidence_id=OUTSIDE_BUNDLE_ID))

    assert failure.stage is AIValidationStage.CITATION_ID_VALIDATION
    assert failure.code is AIValidationFailureCode.CITATION_NOT_IN_BUNDLE


def test_id_that_may_exist_elsewhere_but_was_not_supplied_is_rejected() -> None:
    # The guard has no database access by design. Bundle membership is the only
    # citation authority, so a canonical ID outside this request is still invalid.
    failure = _reject(_candidate(evidence_id=OUTSIDE_BUNDLE_ID), _bundle())

    assert failure.code is AIValidationFailureCode.CITATION_NOT_IN_BUNDLE


def test_citation_validation_runs_before_claim_policy() -> None:
    failure = _reject(
        _candidate(
            evidence_id=OUTSIDE_BUNDLE_ID,
            text="The proven root cause is pump cavitation.",
        )
    )

    assert failure.stage is AIValidationStage.CITATION_ID_VALIDATION
    assert failure.code is AIValidationFailureCode.CITATION_NOT_IN_BUNDLE


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (
            "The proven root cause is pump cavitation.",
            AIValidationFailureCode.ROOT_CAUSE_AUTHORITY_EXCEEDED,
        ),
        (
            "The machine is certified safe to operate.",
            AIValidationFailureCode.MAINTENANCE_CERTIFICATION_PROHIBITED,
        ),
        (
            "The repair has permanently fixed the issue.",
            AIValidationFailureCode.REPAIR_GUARANTEE_PROHIBITED,
        ),
        (
            "The hydraulic system will fail again.",
            AIValidationFailureCode.FAILURE_GUARANTEE_PROHIBITED,
        ),
        (
            "The hydraulic system will not fail again.",
            AIValidationFailureCode.NO_FAILURE_GUARANTEE_PROHIBITED,
        ),
        (
            "Replace the hydraulic pump immediately.",
            AIValidationFailureCode.AUTHORITATIVE_MAINTENANCE_INSTRUCTION,
        ),
        (
            "The incident must be closed now.",
            AIValidationFailureCode.INCIDENT_STATE_TRANSITION_PROHIBITED,
        ),
        (
            "Reassign the owner to the maintenance supervisor.",
            AIValidationFailureCode.OWNERSHIP_CHANGE_PROHIBITED,
        ),
        (
            "Raise the severity to critical.",
            AIValidationFailureCode.SEVERITY_CHANGE_PROHIBITED,
        ),
    ],
)
def test_adversarial_authority_claims_are_rejected(
    text: str,
    code: AIValidationFailureCode,
) -> None:
    failure = _reject(_candidate(text=text))

    assert failure.stage is AIValidationStage.CLAIM_POLICY_VALIDATION
    assert failure.code is code


def test_forbidden_authority_claim_in_summary_is_rejected() -> None:
    failure = _reject(
        _candidate(summary="The definitive root cause is hydraulic pump cavitation.")
    )

    assert failure.stage is AIValidationStage.CLAIM_POLICY_VALIDATION
    assert failure.code is AIValidationFailureCode.ROOT_CAUSE_AUTHORITY_EXCEEDED
    assert failure.claim_index is None


def test_valid_citation_does_not_make_invalid_claim_valid() -> None:
    failure = _reject(
        _candidate(
            evidence_id=EVIDENCE_ID,
            text="The repair has fully resolved the fault.",
        )
    )

    assert failure.stage is AIValidationStage.CLAIM_POLICY_VALIDATION
    assert failure.code is AIValidationFailureCode.REPAIR_GUARANTEE_PROHIBITED


def test_verification_pass_claim_requires_deterministic_bundle_support() -> None:
    failure = _reject(
        _candidate(
            claim_type="VERIFICATION_PASSED",
            text="Verification passed.",
        ),
        _bundle(),
    )

    assert failure.code is AIValidationFailureCode.VERIFICATION_OUTCOME_NOT_ESTABLISHED


def test_verification_failed_claim_requires_deterministic_bundle_support() -> None:
    failure = _reject(
        _candidate(
            claim_type="VERIFICATION_FAILED",
            text="Verification failed because recurrence was detected.",
        ),
        _bundle(),
    )

    assert failure.code is AIValidationFailureCode.VERIFICATION_OUTCOME_NOT_ESTABLISHED


def test_recurrence_claim_requires_deterministic_bundle_support() -> None:
    failure = _reject(
        _candidate(
            claim_type="RECURRENCE_RECORDED",
            text="Recurrence was recorded.",
        ),
        _bundle(),
    )

    assert failure.code is AIValidationFailureCode.RECURRENCE_NOT_ESTABLISHED


def test_verification_pass_claim_is_allowed_when_bundle_establishes_success() -> None:
    result = AIValidationGuard().validate(
        _candidate(
            claim_type="VERIFICATION_PASSED",
            text="Verification passed according to the deterministic verification context.",
        ),
        _bundle(verification_result=VerificationRunResult.SUCCEEDED),
    )

    assert result.status is AIValidationStatus.VALIDATED


def test_verification_failed_claim_is_allowed_when_bundle_establishes_recurrence() -> None:
    result = AIValidationGuard().validate(
        _candidate(
            claim_type="VERIFICATION_FAILED",
            text="Verification failed because the deterministic run detected recurrence.",
        ),
        _bundle(verification_result=VerificationRunResult.RECURRENCE_DETECTED),
    )

    assert result.status is AIValidationStatus.VALIDATED


def test_recurrence_claim_is_allowed_when_bundle_has_recurrence_relationship() -> None:
    result = AIValidationGuard().validate(
        _candidate(
            claim_type="RECURRENCE_RECORDED",
            text="Recurrence was recorded in the supplied deterministic context.",
        ),
        _bundle(relationship_type=IncidentEvidenceRelationshipType.RECURRENCE),
    )

    assert result.status is AIValidationStatus.VALIDATED


@pytest.mark.parametrize(
    "text",
    [
        "The root cause is not established by the supplied evidence.",
        "The issue may recur; the bundle does not establish a future outcome.",
        "A maintenance record says the filter was replaced.",
        "The incident status was reported in an observation, but no transition is recommended.",
    ],
)
def test_non_authoritative_uncertainty_and_factual_reporting_are_allowed(text: str) -> None:
    result = AIValidationGuard().validate(_candidate(text=text), _bundle())

    assert result.status is AIValidationStatus.VALIDATED


def test_guard_has_no_model_database_or_qdrant_capabilities() -> None:
    public = {
        name
        for name, member in inspect.getmembers(AIValidationGuard)
        if not name.startswith("_") and callable(member)
    }

    assert public == {"validate"}
