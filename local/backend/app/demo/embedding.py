"""Deterministic demo-only local text embedding.

This exists solely so a presentation ZIP can exercise the real Qdrant retrieval
path without a model download. Production/demo_mode=false continues to use the
pinned FastEmbed provider.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

from app.integrations.embeddings.base import EmbeddingKind, EmbeddingVector, validate_embedding_text
from app.demo.fixtures import DEMO_EMBEDDING_DIMENSION, DEMO_EMBEDDING_MODEL, DEMO_EMBEDDING_PROVIDER

_TOKEN = re.compile(r"[a-z0-9]+")


class DemoHashEmbeddingProvider:
    provider_name = DEMO_EMBEDDING_PROVIDER

    def _embed(self, text: str, kind: EmbeddingKind) -> EmbeddingVector:
        normalized = validate_embedding_text(text).lower()
        values = [0.0] * DEMO_EMBEDDING_DIMENSION
        tokens = _TOKEN.findall(normalized)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % DEMO_EMBEDDING_DIMENSION
            sign = 1.0 if digest[4] & 1 else -1.0
            values[index] += sign
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        values = [value / norm for value in values]
        return EmbeddingVector.validated(
            values,
            provider=DEMO_EMBEDDING_PROVIDER,
            model=DEMO_EMBEDDING_MODEL,
            kind=kind,
        )

    def embed_document(self, text: str) -> EmbeddingVector:
        return self._embed(text, EmbeddingKind.DOCUMENT)

    def embed_query(self, text: str) -> EmbeddingVector:
        return self._embed(text, EmbeddingKind.QUERY)

    def embed_documents(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        return [self.embed_document(text) for text in texts]

    def probe_availability(self) -> bool:
        return True
