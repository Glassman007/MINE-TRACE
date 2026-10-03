"""Typed results for optional semantic historical retrieval."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SemanticHistoryFailure(StrEnum):
    SEMANTIC_SEARCH_DISABLED = "SEMANTIC_SEARCH_DISABLED"
    EMBEDDING_UNAVAILABLE = "EMBEDDING_UNAVAILABLE"
    SEMANTIC_INDEX_UNAVAILABLE = "SEMANTIC_INDEX_UNAVAILABLE"


class SemanticHistoryEvidence(BaseModel):
    """Canonical evidence hydrated after a Qdrant similarity candidate.

    ``similarity_score`` is derived Qdrant ranking metadata only. It is not a
    confidence score, factual probability, probability of the same failure,
    probability of root cause, or proof of equivalence.
    """

    model_config = ConfigDict(extra="forbid")

    match_type: Literal["SEMANTIC"] = "SEMANTIC"
    evidence_id: UUID
    machine_id: UUID
    component_id: UUID | None
    evidence_type: str
    original_timestamp: datetime
    canonical_event_type: str
    canonical_payload: dict[str, Any]
    provenance: dict[str, Any]
    similarity_score: float = Field(
        description=(
            "Raw Qdrant ranking score for the configured distance metric; not "
            "confidence, probability, or factual equivalence."
        )
    )


class SemanticHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    results: list[SemanticHistoryEvidence] = Field(default_factory=list)
    failure: SemanticHistoryFailure | None = None
