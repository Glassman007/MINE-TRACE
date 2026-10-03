"""Typed, non-authoritative Qdrant service results for MINE-TRACE.

Qdrant contains derived semantic state only. None of the types in this module
represent canonical evidence, provenance, incident state, verification,
handover, audit history, or recurrence truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.integrations.semantic import SemanticIndexHit


class QdrantAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class QdrantDistance(StrEnum):
    COSINE = "cosine"
    DOT = "dot"
    EUCLID = "euclid"
    MANHATTAN = "manhattan"


@dataclass(frozen=True, slots=True)
class QdrantConnectivityResult:
    availability: QdrantAvailability
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class QdrantCollectionsResult:
    availability: QdrantAvailability
    collections: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class QdrantCollectionResult:
    availability: QdrantAvailability
    collection_name: str
    exists: bool
    compatible: bool | None
    expected_vector_size: int
    actual_vector_size: int | None
    expected_distance: QdrantDistance
    actual_distance: QdrantDistance | None
    created: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class QdrantMutationResult:
    availability: QdrantAvailability
    succeeded: bool
    point_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class QdrantSearchResult:
    """Derived vector-ranking result.

    ``SemanticIndexHit.score`` is a raw Qdrant ranking score for the configured
    distance function. It is not a confidence value, factual probability, or
    evidence-strength measurement.
    """

    availability: QdrantAvailability
    hits: tuple[SemanticIndexHit, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class QdrantPointMetadata:
    point_id: str
    evidence_id: UUID
    machine_id: UUID
    component_id: UUID | None
    evidence_type: str


@dataclass(frozen=True, slots=True)
class QdrantMetadataSearchResult:
    availability: QdrantAvailability
    points: tuple[QdrantPointMetadata, ...] = ()
    next_offset: object | None = None
    reason: str | None = None


class QdrantServiceError(RuntimeError):
    """Base class for Qdrant service failures."""


class QdrantUnavailableError(QdrantServiceError):
    """Compatibility exception used by the legacy SemanticIndex adapter."""


class QdrantCollectionCompatibilityError(QdrantServiceError):
    """Raised only by compatibility wrappers when a collection is incompatible."""


__all__ = [
    "QdrantAvailability",
    "QdrantCollectionCompatibilityError",
    "QdrantCollectionResult",
    "QdrantCollectionsResult",
    "QdrantConnectivityResult",
    "QdrantDistance",
    "QdrantMetadataSearchResult",
    "QdrantMutationResult",
    "QdrantPointMetadata",
    "QdrantSearchResult",
    "QdrantServiceError",
    "QdrantUnavailableError",
]
