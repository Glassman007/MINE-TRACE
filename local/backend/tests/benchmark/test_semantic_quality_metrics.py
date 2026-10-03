from pathlib import Path

import pytest

from benchmarks.semantic_quality.runner import (
    ScoreLabel,
    aggregate_metrics,
    analyze_thresholds,
    compute_query_metrics,
    load_dataset,
)


DATASET = Path(__file__).resolve().parents[2] / "benchmarks" / "semantic_quality" / "dataset"


def test_dataset_is_valid_and_has_required_coverage():
    evidence, queries, manifest = load_dataset(DATASET)
    assert len(evidence) == 36
    assert len(queries) == 20
    labels = {label for query in queries for label in query["labels"]}
    required = {
        "paraphrase",
        "abbreviation",
        "technician_terminology",
        "operator_terminology",
        "different_wording_same_symptom",
        "semantically_similar_causally_unrelated",
        "different_machine_distractor",
        "same_machine_record",
        "different_component_distractor",
        "same_component_history",
    }
    assert required <= labels
    assert manifest["evidence_count"] == 36
    assert manifest["query_count"] == 20


def test_query_metric_math_and_scope_checks():
    result = compute_query_metrics(
        query_id="q",
        category="PARAPHRASE",
        labels=("paraphrase",),
        returned_ids=("a", "x", "b"),
        scores=(0.9, 0.8, 0.7),
        result_machine_ids=("m", "m", "m"),
        result_component_ids=("c", "c", "c"),
        relevant_ids=("a", "b"),
        distractor_ids=("x", "z"),
        expected_machine_id="m",
        expected_component_id="c",
        top_k=3,
        available=True,
        failure=None,
        qdrant_search_latency_ms=7.5,
        end_to_end_latency_ms=12.0,
    )
    assert result.recall_at_k == 1.0
    assert result.precision_at_k == pytest.approx(2 / 3)
    assert result.reciprocal_rank == 1.0
    assert result.distractor_rejection == 0.5
    assert result.same_machine_scope_ok is True
    assert result.same_component_scope_ok is True


def test_precision_at_k_uses_requested_k_denominator():
    result = compute_query_metrics(
        query_id="q",
        category="X",
        labels=(),
        returned_ids=("a",),
        scores=(0.9,),
        result_machine_ids=("m",),
        result_component_ids=("c",),
        relevant_ids=("a",),
        distractor_ids=(),
        expected_machine_id="m",
        expected_component_id="c",
        top_k=5,
        available=True,
        failure=None,
        qdrant_search_latency_ms=1.0,
        end_to_end_latency_ms=2.0,
    )
    assert result.precision_at_k == 0.2
    assert result.recall_at_k == 1.0


def test_mrr_uses_first_relevant_rank():
    result = compute_query_metrics(
        query_id="q",
        category="X",
        labels=(),
        returned_ids=("x", "a", "b"),
        scores=(0.95, 0.9, 0.8),
        result_machine_ids=("m", "m", "m"),
        result_component_ids=("c", "c", "c"),
        relevant_ids=("a", "b"),
        distractor_ids=("x",),
        expected_machine_id="m",
        expected_component_id="c",
        top_k=3,
        available=True,
        failure=None,
        qdrant_search_latency_ms=1.0,
        end_to_end_latency_ms=2.0,
    )
    assert result.reciprocal_rank == 0.5


def test_scope_violation_is_observable():
    result = compute_query_metrics(
        query_id="q",
        category="X",
        labels=(),
        returned_ids=("a",),
        scores=(0.9,),
        result_machine_ids=("other",),
        result_component_ids=("other-c",),
        relevant_ids=("a",),
        distractor_ids=(),
        expected_machine_id="m",
        expected_component_id="c",
        top_k=1,
        available=True,
        failure=None,
        qdrant_search_latency_ms=1.0,
        end_to_end_latency_ms=2.0,
    )
    assert result.same_machine_scope_ok is False
    assert result.same_component_scope_ok is False


def test_threshold_analysis_reports_measured_tradeoffs_without_selection():
    rows = analyze_thresholds(
        [
            ScoreLabel("q1", "a", 0.90, True, False),
            ScoreLabel("q1", "b", 0.80, False, True),
            ScoreLabel("q2", "c", 0.70, True, False),
            ScoreLabel("q2", "d", 0.60, False, True),
        ],
        total_relevant_pairs=2,
    )
    assert rows
    highest = rows[0]
    assert highest["threshold"] == 0.90
    assert highest["precision"] == 1.0
    assert highest["recall"] == 0.5
    assert all("confidence" not in key for row in rows for key in row)


def test_threshold_analysis_counts_unretrieved_relevant_pairs_as_recall_loss():
    rows = analyze_thresholds(
        [ScoreLabel("q1", "a", 0.9, True, False)],
        total_relevant_pairs=3,
    )
    assert rows[0]["recall"] == pytest.approx(1 / 3)


def test_aggregate_metrics_includes_latency_summaries():
    one = compute_query_metrics(
        query_id="q1",
        category="X",
        labels=(),
        returned_ids=("a",),
        scores=(0.9,),
        result_machine_ids=("m",),
        result_component_ids=("c",),
        relevant_ids=("a",),
        distractor_ids=(),
        expected_machine_id="m",
        expected_component_id="c",
        top_k=1,
        available=True,
        failure=None,
        qdrant_search_latency_ms=5.0,
        end_to_end_latency_ms=10.0,
    )
    two = compute_query_metrics(
        query_id="q2",
        category="X",
        labels=(),
        returned_ids=("b",),
        scores=(0.8,),
        result_machine_ids=("m",),
        result_component_ids=("c",),
        relevant_ids=("b",),
        distractor_ids=(),
        expected_machine_id="m",
        expected_component_id="c",
        top_k=1,
        available=True,
        failure=None,
        qdrant_search_latency_ms=15.0,
        end_to_end_latency_ms=20.0,
    )
    metrics = aggregate_metrics([one, two], top_k=1)
    assert metrics["recall@1"] == 1.0
    assert metrics["qdrant_search_latency_ms"]["mean"] == 10.0
    assert metrics["end_to_end_retrieval_latency_ms"]["mean"] == 15.0
