"""Natural-language local semantic search contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SemanticSearchFailure(StrEnum):
    SEMANTIC_SEARCH_DISABLED = "SEMANTIC_SEARCH_DISABLED"
    EMBEDDING_UNAVAILABLE = "EMBEDDING_UNAVAILABLE"
    SEMANTIC_INDEX_UNAVAILABLE = "SEMANTIC_INDEX_UNAVAILABLE"
    DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
    SEMANTIC_INDEX_INCOMPATIBLE = "SEMANTIC_INDEX_INCOMPATIBLE"


class SemanticSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    component_id: UUID | None = None
    limit: int = Field(default=10, ge=1, le=100)


class SemanticSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Literal["Semantic"] = "Semantic"
    evidence_id: UUID
    machine_id: UUID
    component_id: UUID | None
    session_id: UUID | None
    incident_id: UUID | None
    source_type: str
    original_timestamp: datetime
    canonical_event_type: str
    canonical_payload: dict[str, Any]
    provenance: dict[str, Any]
    similarity_score: float = Field(
        description=(
            "Raw ranking score from the configured Qdrant distance metric. "
            "Not a probability, root-cause confidence, or proof of common cause."
        )
    )


class SemanticSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    classification: Literal["Semantic"] = "Semantic"
    results: list[SemanticSearchResult] = Field(default_factory=list)
    failure: SemanticSearchFailure | None = None
    reason: str | None = None
