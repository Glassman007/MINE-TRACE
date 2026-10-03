"""Production-shaped semantic retrieval quality benchmark for MINE-TRACE.

This benchmark intentionally exercises the real retrieval boundary:

benchmark query (stored as isolated canonical evaluation evidence)
-> configured embedding provider/model
-> actual Qdrant vector search with machine/component filters
-> candidate evidence IDs
-> canonical PostgreSQL hydration through SemanticHistoryService
-> relevance evaluation

It never uses a standalone cosine-similarity substitute for benchmark scoring.
All benchmark database/Qdrant resources are isolated with a ``mine_trace_bench_``
prefix and are cleaned by default.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import Settings
from app.db.base import Base
from app.integrations.embeddings import build_embedding_provider
from app.integrations.embeddings.qdrant_cloud import QDRANT_CLOUD_INFERENCE_PROVIDER
from app.integrations.qdrant import QdrantAvailability, QdrantDistance, QdrantService
from app.models import ComponentRecord, EvidenceEventRecord, MachineRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.services.semantic_indexing import CanonicalEvidenceIndexingService, SemanticIndexingState
from app.services.semantic_history import SemanticHistoryService

BENCHMARK_PREFIX = "mine_trace_bench_"
DEFAULT_DATASET_DIR = Path(__file__).resolve().parent / "dataset"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"
MODEL_METADATA_PATH = Path(__file__).resolve().parent / "selected_embedding_model.json"


@dataclass(frozen=True, slots=True)
class QueryEvaluation:
    query_id: str
    category: str
    labels: tuple[str, ...]
    available: bool
    failure: str | None
    returned_ids: tuple[str, ...]
    scores: tuple[float, ...]
    relevant_ids: tuple[str, ...]
    distractor_ids: tuple[str, ...]
    relevant_hits: tuple[str, ...]
    distractor_hits: tuple[str, ...]
    recall_at_k: float
    precision_at_k: float
    reciprocal_rank: float
    distractor_rejection: float
    same_machine_scope_ok: bool
    same_component_scope_ok: bool
    component_scoped: bool
    qdrant_search_latency_ms: float | None
    end_to_end_latency_ms: float


@dataclass(frozen=True, slots=True)
class ScoreLabel:
    query_id: str
    evidence_id: str
    score: float
    relevant: bool
    explicit_distractor: bool


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: row must be a JSON object")
        rows.append(value)
    return rows


def load_dataset(dataset_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    evidence = _read_jsonl(dataset_dir / "evidence.jsonl")
    queries = _read_jsonl(dataset_dir / "queries.jsonl")
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    validate_dataset(evidence, queries, manifest)
    return evidence, queries, manifest


def validate_dataset(
    evidence: Sequence[dict[str, Any]],
    queries: Sequence[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    if len(evidence_by_id) != len(evidence):
        raise ValueError("benchmark evidence IDs must be unique")
    query_ids = {row["query_id"] for row in queries}
    if len(query_ids) != len(queries):
        raise ValueError("benchmark query IDs must be unique")
    for row in evidence:
        UUID(row["evidence_id"])
        UUID(row["machine_id"])
        if row.get("component_id"):
            UUID(row["component_id"])
    for row in queries:
        UUID(row["query_evidence_id"])
        UUID(row["machine_id"])
        if row.get("component_id"):
            UUID(row["component_id"])
        relevant = set(row["relevant_evidence_ids"])
        distractors = set(row["distractor_evidence_ids"])
        if not relevant:
            raise ValueError(f"{row['query_id']}: at least one relevant evidence ID is required")
        if relevant & distractors:
            raise ValueError(f"{row['query_id']}: relevant and distractor sets overlap")
        unknown = (relevant | distractors) - evidence_by_id.keys()
        if unknown:
            raise ValueError(f"{row['query_id']}: unknown evidence IDs: {sorted(unknown)}")
        for evidence_id in relevant:
            candidate = evidence_by_id[evidence_id]
            if candidate["machine_id"] != row["machine_id"]:
                raise ValueError(f"{row['query_id']}: relevant evidence crosses machine scope")
            if row.get("component_id") and candidate.get("component_id") != row.get("component_id"):
                raise ValueError(f"{row['query_id']}: relevant evidence crosses component scope")
    if manifest.get("evidence_count") != len(evidence) or manifest.get("query_count") != len(queries):
        raise ValueError("dataset manifest counts do not match JSONL files")


def compute_query_metrics(
    *,
    query_id: str,
    category: str,
    labels: Sequence[str],
    returned_ids: Sequence[str],
    scores: Sequence[float],
    result_machine_ids: Sequence[str],
    result_component_ids: Sequence[str | None],
    relevant_ids: Sequence[str],
    distractor_ids: Sequence[str],
    expected_machine_id: str,
    expected_component_id: str | None,
    top_k: int,
    available: bool,
    failure: str | None,
    qdrant_search_latency_ms: float | None,
    end_to_end_latency_ms: float,
) -> QueryEvaluation:
    relevant = set(relevant_ids)
    distractors = set(distractor_ids)
    top_ids = list(returned_ids[:top_k])
    relevant_hits = tuple(value for value in top_ids if value in relevant)
    distractor_hits = tuple(value for value in top_ids if value in distractors)
    recall = len(set(relevant_hits)) / len(relevant) if relevant else 0.0
    precision = len(relevant_hits) / top_k if top_k else 0.0
    first_rank = next((index for index, value in enumerate(top_ids, 1) if value in relevant), None)
    rr = 1.0 / first_rank if first_rank else 0.0
    rejection = 1.0 - (len(set(distractor_hits)) / len(distractors)) if distractors else 1.0
    same_machine_ok = all(machine == expected_machine_id for machine in result_machine_ids[:top_k])
    same_component_ok = True
    if expected_component_id is not None:
        same_component_ok = all(
            component == expected_component_id for component in result_component_ids[:top_k]
        )
    return QueryEvaluation(
        query_id=query_id,
        category=category,
        labels=tuple(labels),
        available=available,
        failure=failure,
        returned_ids=tuple(top_ids),
        scores=tuple(float(value) for value in scores[:top_k]),
        relevant_ids=tuple(relevant_ids),
        distractor_ids=tuple(distractor_ids),
        relevant_hits=relevant_hits,
        distractor_hits=distractor_hits,
        recall_at_k=recall,
        precision_at_k=precision,
        reciprocal_rank=rr,
        distractor_rejection=rejection,
        same_machine_scope_ok=same_machine_ok,
        same_component_scope_ok=same_component_ok,
        component_scoped=expected_component_id is not None,
        qdrant_search_latency_ms=qdrant_search_latency_ms,
        end_to_end_latency_ms=end_to_end_latency_ms,
    )


def aggregate_metrics(evaluations: Sequence[QueryEvaluation], *, top_k: int) -> dict[str, Any]:
    if not evaluations:
        return {
            "query_count": 0,
            f"recall@{top_k}": None,
            f"precision@{top_k}": None,
            "mrr": None,
            "distractor_rejection": None,
            "same_machine_retrieval_rate": None,
            "same_component_retrieval_rate": None,
            "same_machine_scope_accuracy": None,
            "same_component_scope_accuracy": None,
            "qdrant_search_latency_ms": {},
            "end_to_end_retrieval_latency_ms": {},
        }
    qdrant_latencies = [
        item.qdrant_search_latency_ms
        for item in evaluations
        if item.qdrant_search_latency_ms is not None
    ]
    e2e = [item.end_to_end_latency_ms for item in evaluations]
    component_scoped = [item for item in evaluations if item.component_scoped]
    return {
        "query_count": len(evaluations),
        f"recall@{top_k}": mean(item.recall_at_k for item in evaluations),
        f"precision@{top_k}": mean(item.precision_at_k for item in evaluations),
        "mrr": mean(item.reciprocal_rank for item in evaluations),
        "distractor_rejection": mean(item.distractor_rejection for item in evaluations),
        "same_machine_retrieval_rate": mean(float(bool(item.relevant_hits)) for item in evaluations),
        "same_component_retrieval_rate": mean(float(bool(item.relevant_hits)) for item in component_scoped) if component_scoped else None,
        "same_machine_scope_accuracy": mean(float(item.same_machine_scope_ok) for item in evaluations),
        "same_component_scope_accuracy": mean(float(item.same_component_scope_ok) for item in component_scoped) if component_scoped else None,
        "qdrant_search_latency_ms": _latency_summary(qdrant_latencies),
        "end_to_end_retrieval_latency_ms": _latency_summary(e2e),
    }


def _latency_summary(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "p95": None, "max": None}
    ordered = sorted(float(value) for value in values)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "mean": mean(ordered),
        "median": median(ordered),
        "p95": ordered[p95_index],
        "max": ordered[-1],
    }


def analyze_thresholds(
    score_labels: Sequence[ScoreLabel],
    *,
    total_relevant_pairs: int,
    max_candidates: int = 25,
) -> list[dict[str, Any]]:
    """Return measured score-threshold tradeoffs without selecting production policy.

    MINE-TRACE currently uses cosine distance, where the Qdrant ranking score is
    ordered higher-is-more-similar. Similarity is never converted to confidence.
    """
    if not score_labels:
        return []
    unique = sorted({float(item.score) for item in score_labels}, reverse=True)
    if len(unique) <= max_candidates:
        thresholds = unique
    else:
        indexes = sorted({round(i * (len(unique) - 1) / (max_candidates - 1)) for i in range(max_candidates)})
        thresholds = [unique[index] for index in indexes]
    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        accepted = [item for item in score_labels if item.score >= threshold]
        tp = sum(item.relevant for item in accepted)
        fp = sum(not item.relevant for item in accepted)
        explicit_distractor_accepted = sum(item.explicit_distractor for item in accepted)
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / total_relevant_pairs if total_relevant_pairs else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        rows.append(
            {
                "threshold": threshold,
                "accepted_candidates": len(accepted),
                "true_positive_pairs": tp,
                "false_positive_pairs": fp,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "explicit_distractors_accepted": explicit_distractor_accepted,
            }
        )
    return rows


class QdrantCloudInferenceBridge:
    """Benchmark-only transport that materializes raw vectors via Qdrant Cloud.

    It implements the existing QdrantCloudInferenceClient contract without
    changing application runtime architecture. A separate isolated collection
    receives ``models.Document`` values, Qdrant Cloud performs the configured
    inference, the generated vectors are retrieved, and temporary points are
    deleted. The production-shaped EmbeddingProvider then returns those vectors
    to the normal CanonicalEvidenceIndexingService/QdrantService pipeline.
    """

    def __init__(self, *, client: Any, collection_name: str, vector_size: int, distance: QdrantDistance) -> None:
        self._client = client
        self._collection_name = _guarded_name(collection_name)
        self._vector_size = int(vector_size)
        self._distance = distance
        if self._vector_size <= 0:
            raise ValueError("benchmark vector size must be positive")
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        from qdrant_client import models
        if self._client.collection_exists(collection_name=self._collection_name):
            self._client.delete_collection(collection_name=self._collection_name)
        distance = {
            QdrantDistance.COSINE: models.Distance.COSINE,
            QdrantDistance.DOT: models.Distance.DOT,
            QdrantDistance.EUCLID: models.Distance.EUCLID,
            QdrantDistance.MANHATTAN: models.Distance.MANHATTAN,
        }[self._distance]
        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(size=self._vector_size, distance=distance),
        )

    def embed_documents(self, *, texts: Sequence[str], model: str, timeout_seconds: float) -> Sequence[Sequence[float]]:
        return self._embed(texts=texts, model=model)

    def embed_queries(self, *, texts: Sequence[str], model: str, timeout_seconds: float) -> Sequence[Sequence[float]]:
        return self._embed(texts=texts, model=model)

    def _embed(self, *, texts: Sequence[str], model: str) -> tuple[tuple[float, ...], ...]:
        from qdrant_client import models
        ids = [str(uuid4()) for _ in texts]
        points = [
            models.PointStruct(id=point_id, vector=models.Document(text=value, model=model), payload={"benchmark": True})
            for point_id, value in zip(ids, texts, strict=True)
        ]
        self._client.upsert(collection_name=self._collection_name, points=points, wait=True)
        try:
            retrieved = self._client.retrieve(
                collection_name=self._collection_name,
                ids=ids,
                with_payload=False,
                with_vectors=True,
            )
            by_id = {str(point.id): point for point in retrieved}
            vectors: list[tuple[float, ...]] = []
            for point_id in ids:
                point = by_id.get(point_id)
                if point is None:
                    raise RuntimeError("Qdrant Cloud inference point was not retrievable")
                vector = getattr(point, "vector", None)
                if isinstance(vector, dict):
                    if len(vector) != 1:
                        raise RuntimeError("unexpected named-vector inference response")
                    vector = next(iter(vector.values()))
                if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes, bytearray)):
                    raise RuntimeError("Qdrant Cloud inference did not return a dense vector")
                vectors.append(tuple(float(value) for value in vector))
            return tuple(vectors)
        finally:
            self._client.delete(
                collection_name=self._collection_name,
                points_selector=models.PointIdsList(points=ids),
                wait=True,
            )


class BenchmarkRuntime:
    def __init__(
        self,
        *,
        evidence: Sequence[dict[str, Any]],
        queries: Sequence[dict[str, Any]],
        dataset_manifest: dict[str, Any],
        top_k: int,
        threshold: float | None,
        analysis_k: int,
        results_dir: Path,
        keep_resources: bool,
    ) -> None:
        self.evidence = evidence
        self.queries = queries
        self.dataset_manifest = dataset_manifest
        self.top_k = top_k
        self.threshold = threshold
        self.analysis_k = analysis_k
        self.results_dir = results_dir
        self.keep_resources = keep_resources
        self.settings = Settings()
        self.token = uuid4().hex[:16]
        self.schema_name = _guarded_name(f"{BENCHMARK_PREFIX}{self.token}")
        self.collection_name = _guarded_name(f"{BENCHMARK_PREFIX}{self.token}")
        self.inference_collection_name = _guarded_name(f"{BENCHMARK_PREFIX}{self.token}_inference")
        self.observability = MLAIObservability()
        self._admin_engine = None
        self._engine = None
        self._client = None

    def run(self) -> dict[str, Any]:
        self._validate_runtime_configuration()
        try:
            self._setup_external_resources()
            self._seed_canonical_data()
            self._index_reference_evidence()
            evaluations = self._run_primary_queries()
            score_labels = self._run_threshold_pool()
            return self._write_reports(evaluations, score_labels)
        finally:
            if not self.keep_resources:
                self._cleanup()

    def _validate_runtime_configuration(self) -> None:
        if not self.settings.semantic_search_enabled:
            raise RuntimeError("MINE_TRACE_SEMANTIC_SEARCH_ENABLED must be true for benchmark execution")
        if not self.settings.qdrant_url:
            raise RuntimeError("MINE_TRACE_QDRANT_URL is required for actual Qdrant benchmark execution")
        if not self.settings.embedding_provider or not self.settings.embedding_model:
            raise RuntimeError("configured embedding provider/model are required")
        if self.settings.embedding_provider.strip().lower() != QDRANT_CLOUD_INFERENCE_PROVIDER:
            raise RuntimeError(
                "this benchmark runner currently targets the selected qdrant_cloud_inference provider; "
                f"configured provider is {self.settings.embedding_provider!r}"
            )
        postgres_url = os.getenv("MINE_TRACE_BENCHMARK_POSTGRES_URL")
        if not postgres_url:
            raise RuntimeError("MINE_TRACE_BENCHMARK_POSTGRES_URL is required; production DB is never assumed")
        if self.settings.qdrant_distance != "cosine":
            raise RuntimeError("threshold candidate analysis is currently validated for the selected cosine distance")
        if self.top_k <= 0 or self.top_k > 100 or self.analysis_k < self.top_k or self.analysis_k > 100:
            raise ValueError("top_k must be 1..100 and analysis_k must be between top_k and 100")

    def _setup_external_resources(self) -> None:
        from qdrant_client import QdrantClient
        api_key = self.settings.qdrant_api_key.get_secret_value() if self.settings.qdrant_api_key else None
        self._client = QdrantClient(
            url=self.settings.qdrant_url,
            api_key=api_key,
            timeout=self.settings.qdrant_timeout_seconds,
            cloud_inference=True,
        )
        # Connectivity is verified before any collection is created/deleted.
        self._client.get_collections()

        pg_url = _postgres_driver_url(os.environ["MINE_TRACE_BENCHMARK_POSTGRES_URL"])
        self._admin_engine = create_engine(pg_url, pool_pre_ping=True)
        with self._admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema_name}"'))
        self._engine = create_engine(
            pg_url,
            connect_args={"options": f"-csearch_path={self.schema_name}"},
            pool_pre_ping=True,
        )
        Base.metadata.create_all(
            self._engine,
            tables=[MachineRecord.__table__, ComponentRecord.__table__, EvidenceEventRecord.__table__],
        )
        self.session_factory = sessionmaker(
            bind=self._engine, autoflush=False, expire_on_commit=False, class_=Session
        )
        self.uow_factory = lambda: SQLAlchemyUnitOfWork(self.session_factory)

        metadata = json.loads(MODEL_METADATA_PATH.read_text(encoding="utf-8"))
        if metadata["provider"] != self.settings.embedding_provider or metadata["model"] != self.settings.embedding_model:
            raise RuntimeError(
                "selected_embedding_model.json does not match configured provider/model; "
                "document the new model before benchmarking it"
            )
        vector_size = int(metadata["vector_size"])
        distance = QdrantDistance(self.settings.qdrant_distance)
        bridge = QdrantCloudInferenceBridge(
            client=self._client,
            collection_name=self.inference_collection_name,
            vector_size=vector_size,
            distance=distance,
        )
        self.embedding = build_embedding_provider(
            self.settings,
            qdrant_cloud_client=bridge,
            observability=self.observability,
        )
        self.qdrant = QdrantService(
            collection_name=self.collection_name,
            distance=distance,
            client=self._client,
            observability=self.observability,
        )

    def _seed_canonical_data(self) -> None:
        machine_ids = sorted({row["machine_id"] for row in self.evidence} | {row["machine_id"] for row in self.queries})
        components: dict[str, str] = {}
        for row in [*self.evidence, *self.queries]:
            if row.get("component_id"):
                components[row["component_id"]] = row["machine_id"]
        with self.session_factory() as session:
            for index, machine_id in enumerate(machine_ids, 1):
                session.add(
                    MachineRecord(
                        id=UUID(machine_id),
                        display_name=f"Benchmark Machine {index}",
                        asset_code=f"BENCH-{index}",
                        machine_type="BENCHMARK",
                        site_name="ISOLATED_EVALUATION",
                    )
                )
            for index, (component_id, machine_id) in enumerate(sorted(components.items()), 1):
                session.add(
                    ComponentRecord(
                        id=UUID(component_id),
                        machine_id=UUID(machine_id),
                        display_name=f"Benchmark Component {index}",
                        component_type="BENCHMARK_COMPONENT",
                    )
                )
            for row in self.evidence:
                session.add(_evidence_record(row))
            for row in self.queries:
                session.add(
                    EvidenceEventRecord(
                        id=UUID(row["query_evidence_id"]),
                        machine_id=UUID(row["machine_id"]),
                        component_id=UUID(row["component_id"]) if row.get("component_id") else None,
                        source_type="HUMAN_OBSERVATION",
                        original_source_record_id=f"benchmark-query:{row['query_id']}",
                        original_timestamp=datetime(2026, 10, 1, tzinfo=UTC),
                        ingestion_timestamp=datetime(2026, 10, 1, tzinfo=UTC),
                        canonical_event_type="BENCHMARK_QUERY",
                        canonical_payload={"observation": row["query"]},
                        raw_source_payload={},
                        provenance={"dataset": self.dataset_manifest["dataset_name"], "synthetic": True, "benchmark_query": True},
                    )
                )
            session.commit()

    def _index_reference_evidence(self) -> None:
        indexing = CanonicalEvidenceIndexingService(
            self.uow_factory,
            self.embedding,
            self.qdrant,
            observability=self.observability,
            batch_size=32,
        )
        result = indexing.batch_index([UUID(row["evidence_id"]) for row in self.evidence])
        failures = [item for item in result.results if item.state is not SemanticIndexingState.INDEXED]
        if failures:
            raise RuntimeError(
                "benchmark indexing failed: "
                + ", ".join(f"{item.evidence_id}:{item.state}:{item.reason}" for item in failures[:5])
            )

    def _semantic_service(self, *, top_k: int, threshold: float | None) -> SemanticHistoryService:
        settings = self.settings.model_copy(
            update={
                "qdrant_collection": self.collection_name,
                "semantic_top_k": top_k,
                "semantic_score_threshold": threshold,
            }
        )
        return SemanticHistoryService(
            self.uow_factory,
            self.embedding,
            self.qdrant,
            settings,
            observability=self.observability,
        )

    def _run_primary_queries(self) -> list[QueryEvaluation]:
        service = self._semantic_service(top_k=self.top_k, threshold=self.threshold)
        evaluations: list[QueryEvaluation] = []
        for query in self.queries:
            started = perf_counter()
            response = service.search_similar_history(UUID(query["query_evidence_id"]))
            end_to_end_ms = (perf_counter() - started) * 1000.0
            snapshot = self.observability.snapshot()
            results = response.results
            evaluations.append(
                compute_query_metrics(
                    query_id=query["query_id"],
                    category=query["relevance_category"],
                    labels=query["labels"],
                    returned_ids=[str(item.evidence_id) for item in results],
                    scores=[item.similarity_score for item in results],
                    result_machine_ids=[str(item.machine_id) for item in results],
                    result_component_ids=[str(item.component_id) if item.component_id else None for item in results],
                    relevant_ids=query["relevant_evidence_ids"],
                    distractor_ids=query["distractor_evidence_ids"],
                    expected_machine_id=query["machine_id"],
                    expected_component_id=query.get("component_id"),
                    top_k=self.top_k,
                    available=response.available,
                    failure=response.failure.value if response.failure else None,
                    qdrant_search_latency_ms=snapshot.last_qdrant_search_latency_ms,
                    end_to_end_latency_ms=end_to_end_ms,
                )
            )
        return evaluations

    def _run_threshold_pool(self) -> list[ScoreLabel]:
        service = self._semantic_service(top_k=self.analysis_k, threshold=None)
        labels: list[ScoreLabel] = []
        for query in self.queries:
            response = service.search_similar_history(UUID(query["query_evidence_id"]))
            if not response.available:
                continue
            relevant = set(query["relevant_evidence_ids"])
            distractors = set(query["distractor_evidence_ids"])
            for item in response.results:
                evidence_id = str(item.evidence_id)
                labels.append(
                    ScoreLabel(
                        query_id=query["query_id"],
                        evidence_id=evidence_id,
                        score=float(item.similarity_score),
                        relevant=evidence_id in relevant,
                        explicit_distractor=evidence_id in distractors,
                    )
                )
        return labels

    def _write_reports(self, evaluations: Sequence[QueryEvaluation], score_labels: Sequence[ScoreLabel]) -> dict[str, Any]:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        aggregate = aggregate_metrics(evaluations, top_k=self.top_k)
        category_groups: dict[str, list[QueryEvaluation]] = defaultdict(list)
        for item in evaluations:
            category_groups[item.category].append(item)
        by_category = {
            category: aggregate_metrics(rows, top_k=self.top_k)
            for category, rows in sorted(category_groups.items())
        }
        total_relevant = sum(len(set(query["relevant_evidence_ids"])) for query in self.queries)
        threshold_rows = analyze_thresholds(score_labels, total_relevant_pairs=total_relevant)
        relevant_scores = [item.score for item in score_labels if item.relevant]
        irrelevant_scores = [item.score for item in score_labels if not item.relevant]
        explicit_distractor_scores = [item.score for item in score_labels if item.explicit_distractor]
        score_distributions = {
            "relevant": _distribution(relevant_scores),
            "irrelevant": _distribution(irrelevant_scores),
            "explicit_distractor": _distribution(explicit_distractor_scores),
        }
        failed = [
            item for item in evaluations
            if (not item.available)
            or item.recall_at_k < 1.0
            or item.distractor_hits
            or not item.same_machine_scope_ok
            or not item.same_component_scope_ok
        ]
        payload = {
            "status": "COMPLETED",
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset": self.dataset_manifest["dataset_name"],
            "embedding_provider": self.settings.embedding_provider,
            "embedding_model": self.settings.embedding_model,
            "distance": self.settings.qdrant_distance,
            "top_k": self.top_k,
            "configured_threshold": self.threshold,
            "threshold_analysis_k": self.analysis_k,
            "metrics": aggregate,
            "metrics_by_category": by_category,
            "score_distributions": score_distributions,
            "threshold_candidates": threshold_rows,
            "threshold_selected": None,
            "threshold_policy": "No production threshold is selected automatically by this benchmark.",
        }
        (self.results_dir / "metrics_report.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (self.results_dir / "query_results.jsonl").write_text(
            "\n".join(json.dumps(asdict(item), sort_keys=True) for item in evaluations) + "\n",
            encoding="utf-8",
        )
        (self.results_dir / "failed_queries.jsonl").write_text(
            "\n".join(json.dumps(asdict(item), sort_keys=True) for item in failed) + ("\n" if failed else ""),
            encoding="utf-8",
        )
        (self.results_dir / "threshold_analysis.json").write_text(
            json.dumps({"score_distributions": score_distributions, "candidates": threshold_rows, "selected_threshold": None}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (self.results_dir / "metrics_report.md").write_text(_metrics_markdown(payload), encoding="utf-8")
        (self.results_dir / "failed_queries.md").write_text(_failed_markdown(failed), encoding="utf-8")
        (self.results_dir / "threshold_analysis.md").write_text(_threshold_markdown(payload), encoding="utf-8")
        return payload

    def _cleanup(self) -> None:
        if self._client is not None:
            for name in (self.collection_name, self.inference_collection_name):
                _guarded_name(name)
                try:
                    if self._client.collection_exists(collection_name=name):
                        self._client.delete_collection(collection_name=name)
                except Exception:
                    pass
        if self._engine is not None:
            self._engine.dispose()
        if self._admin_engine is not None:
            try:
                _guarded_name(self.schema_name)
                with self._admin_engine.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema_name}" CASCADE'))
            finally:
                self._admin_engine.dispose()


def _evidence_record(row: dict[str, Any]) -> EvidenceEventRecord:
    timestamp = datetime.fromisoformat(row["original_timestamp"].replace("Z", "+00:00"))
    return EvidenceEventRecord(
        id=UUID(row["evidence_id"]),
        machine_id=UUID(row["machine_id"]),
        component_id=UUID(row["component_id"]) if row.get("component_id") else None,
        source_type=row["evidence_type"],
        original_source_record_id=f"benchmark:{row['evidence_key']}",
        original_timestamp=timestamp,
        ingestion_timestamp=timestamp,
        canonical_event_type=row["canonical_event_type"],
        canonical_payload=row["canonical_payload"],
        raw_source_payload={},
        provenance=row["provenance"],
    )


def _guarded_name(value: str) -> str:
    if not value.startswith(BENCHMARK_PREFIX):
        raise RuntimeError(f"refusing destructive benchmark operation for {value!r}")
    return value


def _postgres_driver_url(url: str) -> str:
    return "postgresql+psycopg://" + url.removeprefix("postgresql://") if url.startswith("postgresql://") else url


def _distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None, "mean": None}
    ordered = sorted(float(v) for v in values)
    def pct(p: float) -> float:
        index = round((len(ordered) - 1) * p)
        return ordered[index]
    return {
        "count": len(ordered), "min": ordered[0], "p25": pct(0.25), "median": median(ordered),
        "p75": pct(0.75), "max": ordered[-1], "mean": mean(ordered),
    }


def _metrics_markdown(payload: dict[str, Any]) -> str:
    m = payload["metrics"]
    k = payload["top_k"]
    return f"""# MINE-TRACE Semantic Quality Metrics\n\nStatus: **{payload['status']}**  \nDataset: `{payload['dataset']}`  \nEmbedding: `{payload['embedding_provider']} / {payload['embedding_model']}`  \nDistance: `{payload['distance']}`  \nTop-K: `{k}`  \nConfigured threshold: `{payload['configured_threshold']}`\n\n| Metric | Value |\n|---|---:|\n| Recall@{k} | {m[f'recall@{k}']:.4f} |\n| Precision@{k} | {m[f'precision@{k}']:.4f} |\n| MRR | {m['mrr']:.4f} |\n| Distractor rejection | {m['distractor_rejection']:.4f} |\n| Same-machine retrieval rate | {m['same_machine_retrieval_rate']:.4f} |\n| Same-component retrieval rate | {m['same_component_retrieval_rate']:.4f} |\n| Same-machine scope accuracy | {m['same_machine_scope_accuracy']:.4f} |\n| Same-component scope accuracy | {m['same_component_scope_accuracy']:.4f} |\n\n## Latency\n\nQdrant search latency (ms): `{json.dumps(m['qdrant_search_latency_ms'], sort_keys=True)}`  \nEnd-to-end retrieval latency (ms): `{json.dumps(m['end_to_end_retrieval_latency_ms'], sort_keys=True)}`\n\nSimilarity scores are Qdrant ranking values only. They are not confidence or factual probability.\n"""


def _failed_markdown(failed: Sequence[QueryEvaluation]) -> str:
    lines = ["# MINE-TRACE Failed-Query Report", "", f"Failed/degraded queries: **{len(failed)}**", ""]
    if not failed:
        lines.append("No query met the failure criteria for this run.")
        return "\n".join(lines) + "\n"
    for item in failed:
        lines.extend([
            f"## {item.query_id} — {item.category}",
            f"- available: `{item.available}`",
            f"- failure: `{item.failure}`",
            f"- recall: `{item.recall_at_k:.4f}`",
            f"- precision: `{item.precision_at_k:.4f}`",
            f"- relevant hits: `{list(item.relevant_hits)}`",
            f"- distractor hits: `{list(item.distractor_hits)}`",
            "",
        ])
    return "\n".join(lines)


def _threshold_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# MINE-TRACE Threshold Analysis",
        "",
        "No production similarity threshold is selected by this benchmark.",
        "Similarity score remains ranking metadata, not confidence/probability.",
        "",
        "## Score distributions",
        "",
        "```json",
        json.dumps(payload["score_distributions"], indent=2, sort_keys=True),
        "```",
        "",
        "## Candidate thresholds and measured tradeoffs",
        "",
        "| Threshold | Precision | Recall | F1 | FP | Explicit distractors accepted |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["threshold_candidates"]:
        lines.append(
            f"| {row['threshold']:.6f} | {row['precision']:.4f} | {row['recall']:.4f} | {row['f1']:.4f} | {row['false_positive_pairs']} | {row['explicit_distractors_accepted']} |"
        )
    return "\n".join(lines) + "\n"


def write_not_run_reports(results_dir: Path, *, reason: str, dataset_manifest: dict[str, Any]) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "NOT_RUN",
        "reason": reason,
        "dataset": dataset_manifest.get("dataset_name"),
        "metrics": None,
        "threshold_candidates": [],
        "selected_threshold": None,
        "statement": "No numeric semantic-quality result is fabricated when actual configured Qdrant/embedding/PostgreSQL resources are unavailable.",
    }
    (results_dir / "metrics_report.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (results_dir / "metrics_report.md").write_text(
        "# MINE-TRACE Semantic Quality Metrics\n\n"
        "Status: **NOT RUN**\n\n"
        f"Reason: {reason}\n\n"
        "No Recall@K, Precision@K, MRR, latency, or threshold values are reported because the actual production-shaped external pipeline was not available in this execution environment.\n",
        encoding="utf-8",
    )
    (results_dir / "failed_queries.jsonl").write_text("", encoding="utf-8")
    (results_dir / "failed_queries.md").write_text(
        "# MINE-TRACE Failed-Query Report\n\nStatus: **NOT RUN**. Query failures cannot be assessed without executing the actual pipeline.\n",
        encoding="utf-8",
    )
    (results_dir / "threshold_analysis.json").write_text(
        json.dumps({"status":"NOT_RUN","reason":reason,"score_distributions":None,"candidates":[],"selected_threshold":None}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (results_dir / "threshold_analysis.md").write_text(
        "# MINE-TRACE Threshold Analysis\n\nStatus: **NOT RUN**. No threshold was guessed or selected. Score distributions require the configured embedding model and actual Qdrant search.\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--top-k", type=int, default=None, help="Primary evaluation K; defaults to MINE_TRACE_SEMANTIC_TOP_K")
    parser.add_argument("--threshold", type=float, default=None, help="Optional configured score threshold; omitted means no threshold")
    parser.add_argument("--analysis-k", type=int, default=20, help="Larger Qdrant candidate pool used only for threshold score-distribution analysis")
    parser.add_argument("--keep-resources", action="store_true", help="Keep isolated benchmark schema/collections for inspection")
    parser.add_argument("--validate-dataset-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence, queries, manifest = load_dataset(args.dataset_dir)
    if args.validate_dataset_only:
        print(json.dumps({"status":"VALID","evidence_count":len(evidence),"query_count":len(queries)}, indent=2))
        return 0
    settings = Settings()
    top_k = args.top_k or settings.semantic_top_k
    threshold = args.threshold if args.threshold is not None else settings.semantic_score_threshold
    runtime = BenchmarkRuntime(
        evidence=evidence,
        queries=queries,
        dataset_manifest=manifest,
        top_k=top_k,
        threshold=threshold,
        analysis_k=max(args.analysis_k, top_k),
        results_dir=args.results_dir,
        keep_resources=args.keep_resources,
    )
    try:
        payload = runtime.run()
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        write_not_run_reports(args.results_dir, reason=reason, dataset_manifest=manifest)
        print(json.dumps({"status":"NOT_RUN","reason":reason}, indent=2))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
