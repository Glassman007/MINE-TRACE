"""Deterministic derived text representation for semantic embedding.

A SemanticDocument contains references to canonical PostgreSQL records plus
rebuildable text. It is never canonical persistence.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NonEmptyString = Annotated[str, Field(min_length=1)]


class SemanticDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID
    machine_id: UUID
    component_id: UUID | None = None
    incident_id: UUID | None = None
    session_id: UUID | None = None
    original_timestamp: datetime
    machine_type: str | None = None
    model: str | None = None
    site: str | None = None
    evidence_type: NonEmptyString
    canonical_event_type: NonEmptyString
    semantic_text: NonEmptyString
