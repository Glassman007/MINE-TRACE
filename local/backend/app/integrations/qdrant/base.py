"""Qdrant-specific marker contract for the optional semantic index.

Qdrant is selected for semantic memory, but it remains a disposable derived
index. The provider-neutral surface lives in ``app.integrations.semantic``.
"""

from typing import Protocol

from app.integrations.semantic import SemanticIndex, SemanticIndexHit


class QdrantSemanticIndex(SemanticIndex, Protocol):
    """Marker protocol for SemanticIndex implementations backed by Qdrant.

    It intentionally adds no authoritative methods beyond SemanticIndex.
    """


__all__ = ["QdrantSemanticIndex", "SemanticIndexHit"]
