"""Provider-neutral contracts for disposable semantic/ML-derived state.

Semantic indexes contain only derived search material. They are never a source
of canonical MINE-TRACE truth. Destroying every index point must leave the
canonical database, evidence, provenance, timelines, incidents, verification,
handover, audit history, linking, and recurrence intact.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SemanticIndexHit:
    """One derived similarity candidate referencing canonical evidence by ID."""

    evidence_id: UUID
    score: float


class SemanticIndex(Protocol):
    """Minimal provider-neutral vector-index boundary.

    The contract accepts derived vectors and canonical identifiers needed for
    filtering. It deliberately exposes no canonical CRUD, incident lifecycle,
    verification, handover, recurrence, severity, ownership, or certification
    operations.
    """

    def upsert_evidence(
        self,
        *,
        evidence_id: UUID,
        machine_id: UUID,
        component_id: UUID | None,
        evidence_type: str,
        vector: Sequence[float],
    ) -> None: ...

    def search(
        self,
        *,
        vector: Sequence[float],
        machine_id: UUID,
        component_id: UUID | None,
        top_k: int,
        min_similarity: float | None,
    ) -> Sequence[SemanticIndexHit]: ...
