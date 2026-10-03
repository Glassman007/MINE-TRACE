"""Deterministic extraction of semantic text from canonical evidence.

The extractor is deliberately read-only. It never writes to the canonical
record, and it does not consult raw source payloads, provenance, incident state,
verification, handover, recurrence, or audit history.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.models import EvidenceEventRecord
from app.schemas.semantic_document import SemanticDocument


class SemanticDocumentExtractor:
    """Build derived semantic documents from eligible canonical text fields.

    The accepted backend stores normalized evidence content in
    ``EvidenceEventRecord.canonical_payload`` as a JSON object rather than in
    source-specific note/description columns. Eligibility is therefore based on
    non-empty string leaves already present in that canonical payload.

    Numeric-only telemetry is intentionally not converted to semantic prose.
    Keys are sorted and sequence order is preserved so the derived text is
    deterministic for the same canonical record.
    """

    def extract(self, evidence: EvidenceEventRecord) -> SemanticDocument | None:
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
            session_id=evidence.session_id,
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

        # bool is intentionally ignored with every other non-string scalar.
        if isinstance(value, Mapping):
            for key in sorted(value, key=lambda item: str(item)):
                child_path = f"{path}.{key}"
                yield from cls._iter_text_items(value[key], child_path)
            return

        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for index, item in enumerate(value):
                yield from cls._iter_text_items(item, f"{path}[{index}]")
