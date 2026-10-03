"""Deterministic validation layers for advisory LLM output.

Two contracts coexist temporarily:

* The accepted legacy functions validate the serialized ``AIAnalysisOutput``
  used by the existing orchestration endpoint.
* ``AIValidationGuard`` validates the new provider-neutral ``AIAnalysis``
  candidate produced by ``AIProvider``.

The new guard is deliberately independent: it has no model, repository,
UnitOfWork, database session, or Qdrant access.  Its only trust inputs are the
candidate output and the exact EvidenceBundle that was supplied to that model
request.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from pydantic import ValidationError

from app.domain.enums import IncidentEvidenceRelationshipType, VerificationRunResult
from app.schemas.ai_analysis import AIAnalysisOutput, AIFallbackReason
from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.schemas.ai_provider import AIAnalysis, AIClaimType
from app.schemas.ai_validation import (
    AIValidationFailure,
    AIValidationFailureCode,
    AIValidationResult,
    AIValidationStage,
    AIValidationStatus,
)
from app.schemas.evidence_bundle import EvidenceBundleResponse


# ---------------------------------------------------------------------------
# New provider-neutral independent guard
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _GuardReject(Exception):
    stage: AIValidationStage
    code: AIValidationFailureCode
    detail: str
    claim_index: int | None = None


_ROOT_CAUSE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:proven|definitive|confirmed|established|certain)\s+(?:the\s+)?root\s+cause\b",
        r"\broot\s+cause\s+(?:is|was|has\s+been)\s+(?!not\b|unknown\b|unclear\b|unproven\b)",
        r"\b(?:failure|incident|problem|issue)\s+(?:is|was|has\s+been)\s+(?:definitively\s+|conclusively\s+)?caused\s+by\b",
    )
)

_MAINTENANCE_CERTIFICATION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:maintenance|repair|machine|equipment)\s+(?:is|was|has\s+been)\s+(?:certified|approved|cleared)\b",
        r"\bcertified\s+(?:safe|fit|ready)\b",
        r"\b(?:safe|fit)\s+to\s+(?:operate|return\s+to\s+service)\b",
    )
)

_REPAIR_GUARANTEE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\brepair\s+(?:has|have|had|was|is)\s+(?:completely\s+|fully\s+|permanently\s+)?(?:solved|fixed|resolved|eliminated)\b",
        r"\b(?:issue|problem|fault)\s+(?:is|was|has\s+been)\s+(?:completely\s+|fully\s+|permanently\s+)?(?:solved|fixed|resolved|eliminated)\b",
        r"\b(?:guaranteed|certain)\b.{0,40}\brepair\b.{0,40}\b(?:worked|succeeded|solved|fixed)\b",
    )
)

_FAILURE_GUARANTEE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:will|shall|is\s+certain\s+to|is\s+guaranteed\s+to)\s+(?:fail|recur|break\s+down|malfunction)\b",
        r"\b(?:failure|recurrence|breakdown)\s+(?:will|shall)\s+(?:occur|happen|recur)\b",
    )
)

_NO_FAILURE_GUARANTEE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:will\s+not|won['’]?t|cannot|can['’]?t|is\s+guaranteed\s+not\s+to)\s+(?:fail|recur|break\s+down|malfunction)\b",
        r"\b(?:no\s+chance|zero\s+risk)\b.{0,35}\b(?:failure|recurrence|breakdown)\b",
        r"\b(?:failure|recurrence|breakdown)\s+(?:will\s+not|cannot|can['’]?t)\s+(?:occur|happen|recur)\b",
    )
)

# These target direct model instructions, not descriptions of already-recorded
# maintenance text such as "the maintenance record says the filter was replaced".
_MAINTENANCE_INSTRUCTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*(?:replace|repair|service|inspect|lubricate|tighten|drain|flush|shut\s+down|stop\s+using|remove\s+from\s+service)\b",
        r"\b(?:must|should|needs?\s+to|has\s+to)\s+(?:replace|repair|service|inspect|lubricate|tighten|drain|flush|shut\s+down|stop\s+using|remove\s+from\s+service)\b",
        r"\b(?:operator|technician|maintenance\s+team)\s+(?:must|should|needs?\s+to|has\s+to)\s+(?:replace|repair|service|inspect|lubricate|tighten|drain|flush|shut\s+down|stop\s+using|remove\s+from\s+service)\b",
    )
)

_INCIDENT_TRANSITION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:set|change|update|transition|move)\b.{0,50}\bincident\s+status\b",
        r"\bincident\b.{0,40}\b(?:must|should|needs?\s+to|can)\s+(?:be\s+)?(?:closed|resolved|verified|reopened|recurred)\b",
        r"\b(?:close|resolve|reopen)\s+(?:the\s+)?incident\b",
    )
)

_OWNERSHIP_CHANGE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:change|set|update|assign|reassign)\b.{0,35}\bowner(?:ship)?\b",
        r"\bowner(?:ship)?\b.{0,35}\b(?:must|should|needs?\s+to)\s+(?:be\s+)?(?:changed|assigned|reassigned)\b",
    )
)

_SEVERITY_CHANGE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:change|set|update|raise|lower|increase|decrease)\b.{0,35}\bseverity\b",
        r"\bseverity\b.{0,35}\b(?:must|should|needs?\s+to)\s+(?:be\s+)?(?:changed|raised|lowered|increased|decreased)\b",
    )
)

_VERIFICATION_PASS_TEXT = re.compile(
    r"\bverification\b.{0,24}\b(?:passed|succeeded|successful|verified)\b",
    re.IGNORECASE,
)
_VERIFICATION_FAIL_TEXT = re.compile(
    r"\bverification\b.{0,24}\b(?:failed|unsuccessful|detected\s+recurrence)\b",
    re.IGNORECASE,
)
_RECURRENCE_ASSERTION_TEXT = re.compile(
    r"\brecurrence\b.{0,24}\b(?:confirmed|recorded|detected|established)\b",
    re.IGNORECASE,
)


def _contains_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    normalized = " ".join(text.split())
    return any(pattern.search(normalized) for pattern in patterns)


def _bundle_verification_support(bundle: EvidenceBundleResponse) -> tuple[bool, bool, bool]:
    started = bool(bundle.verification_context)
    passed = any(
        item.result is VerificationRunResult.SUCCEEDED
        for item in bundle.verification_context
    )
    failed = any(
        item.result is VerificationRunResult.RECURRENCE_DETECTED
        for item in bundle.verification_context
    )
    return started, passed, failed


def _bundle_recurrence_support(bundle: EvidenceBundleResponse) -> bool:
    if any(
        item.relationship_type is IncidentEvidenceRelationshipType.RECURRENCE
        for item in bundle.primary_incident_evidence
    ):
        return True
    return any(
        item.result is VerificationRunResult.RECURRENCE_DETECTED
        for item in bundle.verification_context
    )


def _allowed_provider_evidence_ids(bundle: EvidenceBundleResponse) -> set[UUID]:
    """IDs explicitly exposed inside this exact request bundle.

    No database lookup is performed.  Therefore an ID that happens to exist in
    canonical storage but was not supplied to this model request is rejected.
    """

    ids: set[UUID] = set()
    for item in (
        *bundle.primary_incident_evidence,
        *bundle.selected_exact_history,
        *bundle.selected_semantic_history,
    ):
        ids.add(item.evidence_id)
    for item in bundle.verification_context:
        ids.update(item.evidence_ids)
    for item in bundle.evidence_time_context_snapshots:
        ids.add(item.evidence_id)
    for item in bundle.provenance_index:
        ids.add(item.evidence_id)
    return ids


class AIValidationGuard:
    """Independent deterministic guard for provider-neutral AI output.

    Validation order is fixed and observable:

    1. schema validation
    2. citation-ID validation
    3. claim-policy validation

    The guard never asks the model whether its own answer is safe or correct and
    never consumes model confidence values.
    """

    def __init__(self, observability: MLAIObservability | None = None) -> None:
        self._observability = observability or get_ml_ai_observability()

    def validate(
        self,
        candidate: AIAnalysis | Mapping[str, Any] | object,
        evidence_bundle: EvidenceBundleResponse,
    ) -> AIValidationResult:
        try:
            analysis = self._validate_schema(candidate)
            self._validate_citations(analysis, evidence_bundle)
            self._validate_claim_policy(analysis, evidence_bundle)
        except _GuardReject as exc:
            self._observability.record_ai_rejection(exc.stage.value)
            return AIValidationResult(
                status=AIValidationStatus.REJECTED,
                analysis=None,
                failure=AIValidationFailure(
                    stage=exc.stage,
                    code=exc.code,
                    detail=exc.detail,
                    claim_index=exc.claim_index,
                ),
            )

        return AIValidationResult(
            status=AIValidationStatus.VALIDATED,
            analysis=analysis,
            failure=None,
        )

    @staticmethod
    def _validate_schema(candidate: object) -> AIAnalysis:
        try:
            if isinstance(candidate, AIAnalysis):
                # Re-validate a serialized copy so the guard does not trust that a
                # provider-created Python object bypassed its own schema boundary.
                payload: object = candidate.model_dump(mode="json")
            else:
                payload = candidate
            return AIAnalysis.model_validate(payload)
        except ValidationError as exc:
            malformed_id = any(
                "evidence_ids" in tuple(str(part) for part in error.get("loc", ()))
                and str(error.get("type", "")).startswith("uuid")
                for error in exc.errors()
            )
            raise _GuardReject(
                AIValidationStage.SCHEMA_VALIDATION,
                (
                    AIValidationFailureCode.MALFORMED_EVIDENCE_ID
                    if malformed_id
                    else AIValidationFailureCode.INVALID_SCHEMA
                ),
                (
                    "model output contains a malformed evidence_id"
                    if malformed_id
                    else "model output does not match the AIAnalysis schema"
                ),
            ) from exc
        except (TypeError, ValueError) as exc:
            raise _GuardReject(
                AIValidationStage.SCHEMA_VALIDATION,
                AIValidationFailureCode.INVALID_SCHEMA,
                "model output does not match the AIAnalysis schema",
            ) from exc

    @staticmethod
    def _validate_citations(
        analysis: AIAnalysis,
        bundle: EvidenceBundleResponse,
    ) -> None:
        allowed = _allowed_provider_evidence_ids(bundle)
        for index, claim in enumerate(analysis.claims):
            for evidence_id in claim.evidence_ids:
                if evidence_id not in allowed:
                    raise _GuardReject(
                        AIValidationStage.CITATION_ID_VALIDATION,
                        AIValidationFailureCode.CITATION_NOT_IN_BUNDLE,
                        "claim cites evidence_id that was not supplied in this EvidenceBundle",
                        claim_index=index,
                    )

    @staticmethod
    def _validate_claim_policy(
        analysis: AIAnalysis,
        bundle: EvidenceBundleResponse,
    ) -> None:
        started, verification_passed, verification_failed = _bundle_verification_support(bundle)
        recurrence_supported = _bundle_recurrence_support(bundle)

        # Claim-type authority is validated against deterministic bundle state.
        for index, claim in enumerate(analysis.claims):
            if claim.claim_type is AIClaimType.VERIFICATION_STARTED and not started:
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.VERIFICATION_OUTCOME_NOT_ESTABLISHED,
                    "VERIFICATION_STARTED is not established by the supplied EvidenceBundle",
                    claim_index=index,
                )
            if claim.claim_type is AIClaimType.VERIFICATION_PASSED and not verification_passed:
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.VERIFICATION_OUTCOME_NOT_ESTABLISHED,
                    "VERIFICATION_PASSED is not established by deterministic verification context",
                    claim_index=index,
                )
            if claim.claim_type is AIClaimType.VERIFICATION_FAILED and not verification_failed:
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.VERIFICATION_OUTCOME_NOT_ESTABLISHED,
                    "VERIFICATION_FAILED is not established by deterministic verification context",
                    claim_index=index,
                )
            if claim.claim_type is AIClaimType.RECURRENCE_RECORDED and not recurrence_supported:
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.RECURRENCE_NOT_ESTABLISHED,
                    "RECURRENCE_RECORDED is not established by the supplied EvidenceBundle",
                    claim_index=index,
                )

        # Summary text is policy-checked too; otherwise a model could place an
        # authoritative assertion outside the typed claims list.
        texts: list[tuple[int | None, str]] = [(None, analysis.summary)]
        texts.extend((index, claim.text) for index, claim in enumerate(analysis.claims))

        for claim_index, text in texts:
            normalized = " ".join(text.split())
            if _contains_any(normalized, _ROOT_CAUSE_PATTERNS):
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.ROOT_CAUSE_AUTHORITY_EXCEEDED,
                    "model asserted a definitive root cause not established by deterministic bundle state",
                    claim_index,
                )
            if _contains_any(normalized, _MAINTENANCE_CERTIFICATION_PATTERNS):
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.MAINTENANCE_CERTIFICATION_PROHIBITED,
                    "model attempted maintenance/safety certification",
                    claim_index,
                )
            if _contains_any(normalized, _REPAIR_GUARANTEE_PATTERNS):
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.REPAIR_GUARANTEE_PROHIBITED,
                    "model guaranteed that a repair solved the issue",
                    claim_index,
                )
            if _contains_any(normalized, _FAILURE_GUARANTEE_PATTERNS):
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.FAILURE_GUARANTEE_PROHIBITED,
                    "model guaranteed a future failure/recurrence",
                    claim_index,
                )
            if _contains_any(normalized, _NO_FAILURE_GUARANTEE_PATTERNS):
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.NO_FAILURE_GUARANTEE_PROHIBITED,
                    "model guaranteed absence of future failure/recurrence",
                    claim_index,
                )
            if _contains_any(normalized, _MAINTENANCE_INSTRUCTION_PATTERNS):
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.AUTHORITATIVE_MAINTENANCE_INSTRUCTION,
                    "model issued an authoritative maintenance instruction",
                    claim_index,
                )
            if _contains_any(normalized, _INCIDENT_TRANSITION_PATTERNS):
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.INCIDENT_STATE_TRANSITION_PROHIBITED,
                    "model attempted an incident lifecycle transition",
                    claim_index,
                )
            if _contains_any(normalized, _OWNERSHIP_CHANGE_PATTERNS):
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.OWNERSHIP_CHANGE_PROHIBITED,
                    "model attempted an ownership change",
                    claim_index,
                )
            if _contains_any(normalized, _SEVERITY_CHANGE_PATTERNS):
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.SEVERITY_CHANGE_PROHIBITED,
                    "model attempted a severity change",
                    claim_index,
                )

            if _VERIFICATION_PASS_TEXT.search(normalized) and not verification_passed:
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.VERIFICATION_OUTCOME_NOT_ESTABLISHED,
                    "model asserted verification success not established by deterministic context",
                    claim_index,
                )
            if _VERIFICATION_FAIL_TEXT.search(normalized) and not verification_failed:
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.VERIFICATION_OUTCOME_NOT_ESTABLISHED,
                    "model asserted verification failure not established by deterministic context",
                    claim_index,
                )
            if _RECURRENCE_ASSERTION_TEXT.search(normalized) and not recurrence_supported:
                raise _GuardReject(
                    AIValidationStage.CLAIM_POLICY_VALIDATION,
                    AIValidationFailureCode.RECURRENCE_NOT_ESTABLISHED,
                    "model asserted recurrence not established by deterministic context",
                    claim_index,
                )


# ---------------------------------------------------------------------------
# Accepted legacy validator retained for existing orchestration compatibility.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AIOutputValidationError(ValueError):
    reason: AIFallbackReason
    detail: str

    def __str__(self) -> str:
        return self.detail


def validate_schema(raw_output: str) -> AIAnalysisOutput:
    """Layer 1: JSON parsing followed by strict Pydantic schema validation."""

    try:
        parsed: Any = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AIOutputValidationError(
            AIFallbackReason.INVALID_JSON,
            "LLM output is not valid JSON",
        ) from exc

    try:
        return AIAnalysisOutput.model_validate(parsed)
    except ValidationError as exc:
        raise AIOutputValidationError(
            AIFallbackReason.SCHEMA_VALIDATION_FAILED,
            "LLM output does not match the strict AI analysis schema",
        ) from exc


def allowed_evidence_ids(bundle: EvidenceBundleResponse) -> set[UUID]:
    """Return every evidence identifier explicitly present in the bundle."""

    ids: set[UUID] = set()
    for item in (
        *bundle.primary_incident_evidence,
        *bundle.selected_exact_history,
        *bundle.selected_semantic_history,
    ):
        ids.add(item.evidence_id)
    for item in bundle.verification_context:
        ids.update(item.evidence_ids)
    for item in bundle.evidence_time_context_snapshots:
        ids.add(item.evidence_id)
    for item in bundle.provenance_index:
        ids.add(item.evidence_id)
    return ids


def validate_citations(
    output: AIAnalysisOutput,
    bundle: EvidenceBundleResponse,
) -> None:
    """Layer 2: citations may refer only to evidence IDs in this bundle."""

    allowed = allowed_evidence_ids(bundle)
    cited: set[UUID] = set()
    for claim in output.claims():
        for evidence_id in claim.evidence_ids:
            if evidence_id not in allowed:
                raise AIOutputValidationError(
                    AIFallbackReason.CITATION_VALIDATION_FAILED,
                    f"citation is not present in EvidenceBundle: {evidence_id}",
                )
            cited.add(evidence_id)

    reference_set = set(output.evidence_references)
    if not reference_set.issubset(allowed):
        raise AIOutputValidationError(
            AIFallbackReason.CITATION_VALIDATION_FAILED,
            "evidence_references contains an ID outside the EvidenceBundle",
        )
    if reference_set != cited:
        raise AIOutputValidationError(
            AIFallbackReason.CITATION_VALIDATION_FAILED,
            "evidence_references must exactly match claim citations",
        )


_FORBIDDEN_ACTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:change|set|update|transition|move)\b.{0,50}\bincident\s+status\b",
        r"\bincident\s+status\b.{0,35}\b(?:should|must|needs?\s+to)\s+(?:be\s+)?",
        r"\b(?:close|closing|resolve)\b.{0,30}\bincident\b",
        r"\bincident\b.{0,35}\b(?:should|must|needs?\s+to|can\s+be)\s+(?:be\s+)?closed\b",
        r"\b(?:mark|set|change|transition)\b.{0,35}\bverified\b",
        r"\bincident\b.{0,35}\b(?:should|must|needs?\s+to)\s+(?:be\s+)?verified\b",
        r"\b(?:change|set|update|assign|reassign)\b.{0,35}\bowner\b",
        r"\bowner\b.{0,35}\b(?:should|must|needs?\s+to)\s+be\b",
        r"\b(?:change|set|update|raise|lower|increase|decrease)\b.{0,35}\bseverity\b",
        r"\bseverity\b.{0,35}\b(?:should|must|needs?\s+to)\s+be\b",
        r"\b(?:change|set|update|modify)\b.{0,35}\bdue\s+(?:state|time)\b",
        r"\bdue\s+(?:state|time)\b.{0,35}\b(?:should|must|needs?\s+to)\s+be\b",
        r"\b(?:modify|edit|delete|remove|overwrite|replace)\b.{0,40}\bevidence\b",
        r"\bevidence\b.{0,40}\b(?:modify|edit|delete|remove|overwrite|replace)\b",
        r"\b(?:edit|delete|rewrite|modify|remove|overwrite)\b.{0,40}\baudit(?:\s+history)?\b",
        r"\baudit(?:\s+history)?\b.{0,40}\b(?:edit|delete|rewrite|modify|remove|overwrite)\b",
    )
)


def validate_claim_policy(output: AIAnalysisOutput) -> None:
    """Legacy layer 3: reject text attempting authoritative state mutation."""

    for claim in output.claims():
        normalized = " ".join(claim.text.split())
        if any(pattern.search(normalized) for pattern in _FORBIDDEN_ACTION_PATTERNS):
            raise AIOutputValidationError(
                AIFallbackReason.CLAIM_POLICY_VALIDATION_FAILED,
                "AI output attempted an authoritative backend action",
            )


__all__ = [
    "AIOutputValidationError",
    "AIValidationGuard",
    "allowed_evidence_ids",
    "validate_citations",
    "validate_claim_policy",
    "validate_schema",
]
