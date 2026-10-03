from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.ai_provider import AIClaim


class FleetAIState(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"


class FleetAIAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=8000)
    machine_ids: list[UUID] = Field(default_factory=list, max_length=100)
    incident_ids: list[UUID] = Field(default_factory=list, max_length=100)
    session_ids: list[UUID] = Field(default_factory=list, max_length=100)
    semantic_query: str | None = Field(default=None, max_length=4000)
    semantic_top_k: int = Field(default=5, ge=1, le=20)


class FleetAICitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    provenance: dict[str, JsonValue]


class FleetAIAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: FleetAIState
    provider: str = "groq"
    model: str | None = None
    summary: str | None = None
    claims: list[AIClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[FleetAICitation] = Field(default_factory=list)
    reason: str | None = None
