"""Embedding integration contracts for optional semantic retrieval.

Embedding output is derived state. Providers may read semantic text and return
vectors, but they must never own or mutate canonical MINE-TRACE state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Protocol


class EmbeddingKind(StrEnum):
    DOCUMENT = "DOCUMENT"
    QUERY = "QUERY"


class EmbeddingError(RuntimeError):
    """Base class for embedding-layer failures."""


class EmbeddingInputError(EmbeddingError, ValueError):
    """Raised when semantic text is empty/invalid before provider invocation."""


class EmbeddingProviderUnavailableError(EmbeddingError):
    """Raised when the selected embedding provider cannot be used."""


class EmbeddingTimeoutError(EmbeddingError):
    """Raised when provider inference exceeds its configured timeout."""


class EmbeddingBatchError(EmbeddingError):
    """Raised when a batch cannot be embedded atomically by the provider adapter."""


class InvalidEmbeddingError(EmbeddingError):
    """Raised when a provider returns a malformed numeric vector."""


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    """One materialized dense vector plus non-authoritative model metadata."""

    values: tuple[float, ...]
    provider: str
    model: str
    kind: EmbeddingKind

    @property
    def dimensions(self) -> int:
        return len(self.values)

    @classmethod
    def validated(
        cls,
        values: Sequence[float],
        *,
        provider: str,
        model: str,
        kind: EmbeddingKind,
    ) -> "EmbeddingVector":
        vector = tuple(float(value) for value in values)
        if not vector:
            raise InvalidEmbeddingError("embedding provider returned an empty vector")
        if any(not math.isfinite(value) for value in vector):
            raise InvalidEmbeddingError("embedding provider returned non-finite values")
        return cls(values=vector, provider=provider, model=model, kind=kind)


class EmbeddingProvider(Protocol):
    """Provider-neutral dense embedding boundary.

    Document and query methods are intentionally distinct. A provider adapter
    may choose the same underlying model for both, but callers must not assume
    that all providers/models use interchangeable document/query embeddings.
    """

    def embed_document(self, text: str) -> EmbeddingVector: ...

    def embed_query(self, text: str) -> EmbeddingVector: ...

    def embed_documents(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]: ...


def validate_embedding_text(text: str) -> str:
    if not isinstance(text, str):
        raise EmbeddingInputError("embedding input must be a string")
    normalized = " ".join(text.split())
    if not normalized:
        raise EmbeddingInputError("embedding input must not be empty")
    return normalized
