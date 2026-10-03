from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class SemanticSearchState(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class SemanticMatchType(StrEnum):
    SEMANTIC_SIMILARITY = "SEMANTIC_SIMILARITY"


class FleetSemanticSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    machine_id: UUID | None = None
    component_id: UUID | None = None
    machine_type: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=255)
    site: str | None = Field(default=None, max_length=255)
    start: datetime | None = None
    end: datetime | None = None
    top_k: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def valid_range(self) -> "FleetSemanticSearchRequest":
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("start must be less than or equal to end")
        for name in ("machine_type", "model", "site"):
            value = getattr(self, name)
            if isinstance(value, str):
                value = value.strip()
                setattr(self, name, value or None)
        self.query = self.query.strip()
        if not self.query:
            raise ValueError("query must not be blank")
        return self


class FleetSemanticSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_type: SemanticMatchType = SemanticMatchType.SEMANTIC_SIMILARITY
    similarity_score: float
    evidence_id: UUID
    machine_id: UUID
    component_id: UUID | None
    session_id: UUID | None
    incident_ids: list[UUID]
    machine_type: str | None
    model: str | None
    site: str | None
    source_type: str
    original_timestamp: datetime
    ingestion_timestamp: datetime
    canonical_event_type: str
    canonical_payload: dict[str, JsonValue]
    provenance: dict[str, JsonValue]


class FleetSemanticSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: SemanticSearchState
    reason: str | None = None
    results: list[FleetSemanticSearchResult] = Field(default_factory=list)
