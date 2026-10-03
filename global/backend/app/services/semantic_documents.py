"""Deterministic extraction of eligible language from canonical evidence only."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from uuid import UUID

from app.models import EvidenceEventRecord
from app.schemas.semantic_document import SemanticDocument


class SemanticDocumentExtractor:
    """Create derived semantic text without inventing prose from telemetry."""

    def extract(
        self,
        evidence: EvidenceEventRecord,
        *,
        incident_id: UUID | None = None,
        machine_type: str | None = None,
        model: str | None = None,
        site: str | None = None,
    ) -> SemanticDocument | None:
        text_items = tuple(self._iter_text_items(evidence.canonical_payload, "payload"))
        if not text_items:
            return None
        lines = [
            f"evidence_type: {evidence.source_type}",
            f"canonical_event_type: {evidence.canonical_event_type}",
        ]
        lines.extend(f"{path}: {value}" for path, value in text_items)
        return SemanticDocument(
            evidence_id=evidence.id,
            machine_id=evidence.machine_id,
            component_id=evidence.component_id,
            incident_id=incident_id,
            session_id=evidence.session_id,
            original_timestamp=evidence.original_timestamp,
            machine_type=machine_type,
            model=model,
            site=site,
            evidence_type=evidence.source_type,
            canonical_event_type=evidence.canonical_event_type,
            semantic_text="\n".join(lines),
        )

    def extract_many(
        self,
        evidence_records: Iterable[EvidenceEventRecord],
    ) -> tuple[SemanticDocument, ...]:
        documents: list[SemanticDocument] = []
        for evidence in evidence_records:
            document = self.extract(evidence)
            if document is not None:
                documents.append(document)
        return tuple(documents)

    @classmethod
    def _iter_text_items(cls, value: Any, path: str) -> Iterable[tuple[str, str]]:
        if isinstance(value, str):
            normalized = " ".join(value.split())
            if normalized:
                yield path, normalized
            return
        if isinstance(value, Mapping):
            for key in sorted(value, key=lambda item: str(item)):
                yield from cls._iter_text_items(value[key], f"{path}.{key}")
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, item in enumerate(value):
                yield from cls._iter_text_items(item, f"{path}[{index}]")
