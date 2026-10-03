"""Deterministic derived text representation for semantic embedding.

A SemanticDocument contains references to canonical evidence plus derived text.
It is never canonical persistence and may be discarded/rebuilt at any time.
"""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NonEmptyString = Annotated[str, Field(min_length=1)]


class SemanticDocument(BaseModel):
    """Derived embedding input built only from canonical evidence fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID
    machine_id: UUID
    component_id: UUID | None = None
    session_id: UUID | None = None
    incident_id: UUID | None = None
    evidence_type: NonEmptyString
    canonical_event_type: NonEmptyString
    semantic_text: NonEmptyString
