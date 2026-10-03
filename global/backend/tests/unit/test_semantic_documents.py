from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models import EvidenceEventRecord
from app.services.semantic_documents import SemanticDocumentExtractor


def _evidence(*, payload: dict, source_type: str = "HUMAN_OBSERVATION") -> EvidenceEventRecord:
    return EvidenceEventRecord(
        id=uuid4(),
        machine_id=uuid4(),
        component_id=uuid4(),
        source_type=source_type,
        original_source_record_id="obs-001",
        original_timestamp=datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc),
        canonical_event_type="OPERATOR_OBSERVATION",
        canonical_payload=payload,
        raw_source_payload={"note": "RAW TEXT MUST NOT BE EMBEDDED"},
        provenance={"source_system": "test", "comment": "PROVENANCE MUST NOT BE EMBEDDED"},
    )


def test_semantic_text_uses_only_existing_canonical_string_content_deterministically() -> None:
    evidence = _evidence(
        payload={
            "observation": "  Operator reported   pump whine during loaded lift. ",
            "nested": {"technician_note": "Inspect return filter"},
            "tags": ["hydraulics", "noise"],
            "pressure_kpa": 18200,
            "active": True,
        }
    )
    extractor = SemanticDocumentExtractor()

    first = extractor.extract(evidence)
    second = extractor.extract(evidence)

    assert first is not None
    assert first == second
    assert first.evidence_id == evidence.id
    assert first.machine_id == evidence.machine_id
    assert first.component_id == evidence.component_id
    assert first.evidence_type == "HUMAN_OBSERVATION"
    assert first.semantic_text == (
        "evidence_type: HUMAN_OBSERVATION\n"
        "canonical_event_type: OPERATOR_OBSERVATION\n"
        "payload.nested.technician_note: Inspect return filter\n"
        "payload.observation: Operator reported pump whine during loaded lift.\n"
        "payload.tags[0]: hydraulics\n"
        "payload.tags[1]: noise"
    )
    assert "RAW TEXT MUST NOT BE EMBEDDED" not in first.semantic_text
    assert "PROVENANCE MUST NOT BE EMBEDDED" not in first.semantic_text
    assert "18200" not in first.semantic_text


def test_numeric_only_canonical_payload_is_not_semantic_content() -> None:
    evidence = _evidence(
        payload={"pressure_kpa": 18200, "threshold_kpa": 19000, "active": True},
        source_type="MACHINE_EVENT",
    )

    assert SemanticDocumentExtractor().extract(evidence) is None


def test_empty_strings_are_not_semantic_content() -> None:
    evidence = _evidence(payload={"observation": "   ", "notes": ["\n\t"]})

    assert SemanticDocumentExtractor().extract(evidence) is None


def test_extract_many_skips_ineligible_records_without_creating_new_ids() -> None:
    eligible = _evidence(payload={"observation": "Bearing rumble under load"})
    ineligible = _evidence(payload={"temperature_c": 91})

    documents = SemanticDocumentExtractor().extract_many((eligible, ineligible))

    assert len(documents) == 1
    assert documents[0].evidence_id == eligible.id
