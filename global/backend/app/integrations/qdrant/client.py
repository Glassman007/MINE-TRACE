"""Qdrant service for disposable MINE-TRACE semantic evidence state.

Qdrant is the selected vector database for MINE-TRACE semantic memory. This
module manages only derived vector/index state. Canonical evidence, provenance,
incident state, verification, handover, audit history, exact timelines,
linking, and recurrence remain in the authoritative backend database.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import math
from time import perf_counter
from typing import Any
from uuid import UUID

from app.core.capabilities import CapabilityStatus
from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.core.settings import Settings
from app.integrations.qdrant.base import QdrantSemanticIndex
from app.integrations.qdrant.types import (
    QdrantAvailability,
    QdrantCollectionCompatibilityError,
    QdrantCollectionResult,
    QdrantCollectionsResult,
    QdrantConnectivityResult,
    QdrantDistance,
    QdrantMetadataSearchResult,
    QdrantMutationResult,
    QdrantPointMetadata,
    QdrantSearchResult,
    QdrantUnavailableError,
)
from app.integrations.semantic import SemanticIndexHit


_DISTANCE_MODEL_NAMES: dict[QdrantDistance, str] = {
    QdrantDistance.COSINE: "COSINE",
    QdrantDistance.DOT: "DOT",
    QdrantDistance.EUCLID: "EUCLID",
    QdrantDistance.MANHATTAN: "MANHATTAN",
}


class QdrantService(QdrantSemanticIndex):
    """Concrete qdrant-client service over one semantic-evidence collection.

    The service is intentionally safe to construct without contacting Qdrant.
    Every direct service operation returns a typed availability state on
    connectivity failures. The legacy ``SemanticIndex`` methods remain as thin
    wrappers so accepted semantic-history code can continue to degrade through
    its existing exception boundary until that service is migrated later.
    """

    def __init__(
        self,
        *,
        collection_name: str,
        distance: QdrantDistance | str = QdrantDistance.COSINE,
        url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        client: Any | None = None,
        models_module: Any | None = None,
        observability: MLAIObservability | None = None,
    ) -> None:
        collection_name = collection_name.strip()
        if not collection_name:
            raise ValueError("collection_name must not be blank")
        self._collection_name = collection_name
        self._distance = QdrantDistance(distance)
        self._models_module = models_module
        self._observability = observability or get_ml_ai_observability()

        if client is not None:
            self._client = client
            return

        if not url:
            raise ValueError("Qdrant URL is required when no client is injected")
        from qdrant_client import QdrantClient  # type: ignore[import-not-found]

        self._client = QdrantClient(url=url, api_key=api_key, timeout=timeout_seconds)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        client: Any | None = None,
        models_module: Any | None = None,
        observability: MLAIObservability | None = None,
    ) -> "QdrantService":
        api_key = (
            settings.qdrant_api_key.get_secret_value()
            if settings.qdrant_api_key is not None
            else None
        )
        return cls(
            collection_name=settings.qdrant_collection,
            distance=QdrantDistance(settings.qdrant_distance),
            url=settings.qdrant_url,
            api_key=api_key,
            timeout_seconds=settings.qdrant_timeout_seconds,
            client=client,
            models_module=models_module,
            observability=observability,
        )

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def distance(self) -> QdrantDistance:
        return self._distance

    @staticmethod
    def point_id_for_evidence(evidence_id: UUID) -> str:
        """Use the canonical evidence UUID itself as the deterministic point ID."""

        return str(evidence_id)

    def connectivity(self) -> QdrantConnectivityResult:
        try:
            self._client.get_collections()
        except Exception as exc:
            self._observability.record_qdrant_connectivity_failure()
            self._observability.record_capability(
                "qdrant_semantic", CapabilityStatus.UNAVAILABLE, "qdrant_unavailable"
            )
            return QdrantConnectivityResult(
                availability=QdrantAvailability.UNAVAILABLE,
                reason=self._unavailable_reason(exc),
            )
        self._observability.record_capability(
            "qdrant_semantic", CapabilityStatus.AVAILABLE, "connectivity_verified"
        )
        return QdrantConnectivityResult(QdrantAvailability.AVAILABLE)

    def discover_collections(self) -> QdrantCollectionsResult:
        try:
            response = self._client.get_collections()
            names = tuple(
                sorted(
                    collection.name
                    for collection in (getattr(response, "collections", None) or ())
                    if getattr(collection, "name", None)
                )
            )
        except Exception as exc:
            return QdrantCollectionsResult(
                availability=QdrantAvailability.UNAVAILABLE,
                reason=self._unavailable_reason(exc),
            )
        return QdrantCollectionsResult(
            availability=QdrantAvailability.AVAILABLE,
            collections=names,
        )

    def delete_collection(self) -> QdrantMutationResult:
        """Delete only the derived semantic collection, never canonical data."""

        try:
            exists = bool(
                self._client.collection_exists(collection_name=self._collection_name)
            )
            if exists:
                self._client.delete_collection(collection_name=self._collection_name)
        except Exception as exc:
            return QdrantMutationResult(
                availability=QdrantAvailability.UNAVAILABLE,
                succeeded=False,
                reason=self._unavailable_reason(exc),
            )
        return QdrantMutationResult(
            availability=QdrantAvailability.AVAILABLE,
            succeeded=True,
        )

    def recreate_collection(self, *, vector_size: int) -> QdrantCollectionResult:
        """Replace the disposable collection with an empty compatible one."""

        vector_size = self._validate_vector_size(vector_size)
        try:
            exists = bool(
                self._client.collection_exists(collection_name=self._collection_name)
            )
            if exists:
                self._client.delete_collection(collection_name=self._collection_name)
            models = self._models()
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=self._qdrant_distance_model(models),
                ),
            )
            self._ensure_filter_indexes()
        except Exception as exc:
            return self._collection_unavailable(vector_size, exc)
        return QdrantCollectionResult(
            availability=QdrantAvailability.AVAILABLE,
            collection_name=self._collection_name,
            exists=True,
            compatible=True,
            expected_vector_size=vector_size,
            actual_vector_size=vector_size,
            expected_distance=self._distance,
            actual_distance=self._distance,
            created=True,
        )

    def initialize_collection(self, *, vector_size: int) -> QdrantCollectionResult:
        """Create the dedicated collection if absent, otherwise validate it.

        ``vector_size`` must come from the configured embedding provider/model's
        materialized output (for example ``EmbeddingVector.dimensions``). No
        model-specific dimensionality is hardcoded here.
        """

        vector_size = self._validate_vector_size(vector_size)
        try:
            exists = bool(
                self._client.collection_exists(collection_name=self._collection_name)
            )
            if not exists:
                models = self._models()
                self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=self._qdrant_distance_model(models),
                    ),
                )
                self._ensure_filter_indexes()
                return QdrantCollectionResult(
                    availability=QdrantAvailability.AVAILABLE,
                    collection_name=self._collection_name,
                    exists=True,
                    compatible=True,
                    expected_vector_size=vector_size,
                    actual_vector_size=vector_size,
                    expected_distance=self._distance,
                    actual_distance=self._distance,
                    created=True,
                )
        except Exception as exc:
            return self._collection_unavailable(vector_size, exc)

        result = self.validate_collection(vector_size=vector_size)
        if result.availability is QdrantAvailability.AVAILABLE and result.compatible:
            try:
                self._ensure_filter_indexes()
            except Exception as exc:
                return QdrantCollectionResult(
                    availability=QdrantAvailability.UNAVAILABLE,
                    collection_name=self._collection_name,
                    exists=True,
                    compatible=None,
                    expected_vector_size=vector_size,
                    actual_vector_size=result.actual_vector_size,
                    expected_distance=self._distance,
                    actual_distance=result.actual_distance,
                    reason=self._unavailable_reason(exc),
                )
        return result

    def validate_collection(self, *, vector_size: int) -> QdrantCollectionResult:
        vector_size = self._validate_vector_size(vector_size)
        try:
            exists = bool(
                self._client.collection_exists(collection_name=self._collection_name)
            )
            if not exists:
                return QdrantCollectionResult(
                    availability=QdrantAvailability.AVAILABLE,
                    collection_name=self._collection_name,
                    exists=False,
                    compatible=False,
                    expected_vector_size=vector_size,
                    actual_vector_size=None,
                    expected_distance=self._distance,
                    actual_distance=None,
                    reason="collection_missing",
                )
            info = self._client.get_collection(collection_name=self._collection_name)
        except Exception as exc:
            return self._collection_unavailable(vector_size, exc)

        vectors = getattr(
            getattr(getattr(info, "config", None), "params", None),
            "vectors",
            None,
        )
        if vectors is None or isinstance(vectors, dict):
            return QdrantCollectionResult(
                availability=QdrantAvailability.AVAILABLE,
                collection_name=self._collection_name,
                exists=True,
                compatible=False,
                expected_vector_size=vector_size,
                actual_vector_size=None,
                expected_distance=self._distance,
                actual_distance=None,
                reason="unsupported_or_named_vector_configuration",
            )

        actual_size = getattr(vectors, "size", None)
        try:
            actual_size = int(actual_size) if actual_size is not None else None
        except (TypeError, ValueError):
            actual_size = None
        actual_distance = self._normalize_distance(getattr(vectors, "distance", None))
        compatible = actual_size == vector_size and actual_distance == self._distance
        reason = None
        if not compatible:
            problems: list[str] = []
            if actual_size != vector_size:
                problems.append("vector_size_mismatch")
            if actual_distance != self._distance:
                problems.append("distance_mismatch")
            reason = ",".join(problems) or "collection_incompatible"

        return QdrantCollectionResult(
            availability=QdrantAvailability.AVAILABLE,
            collection_name=self._collection_name,
            exists=True,
            compatible=compatible,
            expected_vector_size=vector_size,
            actual_vector_size=actual_size,
            expected_distance=self._distance,
            actual_distance=actual_distance,
            reason=reason,
        )

    def upsert_vector(
        self,
        *,
        evidence_id: UUID,
        machine_id: UUID,
        component_id: UUID | None,
        evidence_type: str,
        vector: Sequence[float],
    ) -> QdrantMutationResult:
        values = self._validated_vector(vector)
        evidence_type = evidence_type.strip()
        if not evidence_type:
            raise ValueError("evidence_type must not be blank")

        payload: dict[str, str] = {
            "evidence_id": str(evidence_id),
            "machine_id": str(machine_id),
            "evidence_type": evidence_type,
        }
        if component_id is not None:
            payload["component_id"] = str(component_id)

        point_id = self.point_id_for_evidence(evidence_id)
        try:
            models = self._models()
            self._client.upsert(
                collection_name=self._collection_name,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=values,
                        payload=payload,
                    )
                ],
                wait=True,
            )
        except Exception as exc:
            return QdrantMutationResult(
                availability=QdrantAvailability.UNAVAILABLE,
                succeeded=False,
                point_id=point_id,
                reason=self._unavailable_reason(exc),
            )
        return QdrantMutationResult(
            availability=QdrantAvailability.AVAILABLE,
            succeeded=True,
            point_id=point_id,
        )

    def upsert_semantic_document(self, *, document, vector: Sequence[float]) -> QdrantMutationResult:
        """Upsert derived vector plus canonical-reference/filter metadata only."""

        values = self._validated_vector(vector)
        payload: dict[str, object] = {
            "evidence_id": str(document.evidence_id),
            "machine_id": str(document.machine_id),
            "evidence_type": document.evidence_type,
            "original_timestamp": self._rfc3339(document.original_timestamp),
        }
        optional = {
            "component_id": document.component_id,
            "incident_id": document.incident_id,
            "session_id": document.session_id,
            "machine_type": document.machine_type,
            "model": document.model,
            "site": document.site,
        }
        for key, value in optional.items():
            if value is not None:
                payload[key] = str(value) if key.endswith("_id") else value

        point_id = self.point_id_for_evidence(document.evidence_id)
        try:
            models = self._models()
            self._client.upsert(
                collection_name=self._collection_name,
                points=[models.PointStruct(id=point_id, vector=values, payload=payload)],
                wait=True,
            )
        except Exception as exc:
            return QdrantMutationResult(
                availability=QdrantAvailability.UNAVAILABLE,
                succeeded=False,
                point_id=point_id,
                reason=self._unavailable_reason(exc),
            )
        return QdrantMutationResult(
            availability=QdrantAvailability.AVAILABLE,
            succeeded=True,
            point_id=point_id,
        )

    def delete_vector(self, *, evidence_id: UUID) -> QdrantMutationResult:
        """Delete only the derived Qdrant point; canonical evidence is untouched."""

        point_id = self.point_id_for_evidence(evidence_id)
        try:
            models = self._models()
            self._client.delete(
                collection_name=self._collection_name,
                points_selector=models.PointIdsList(points=[point_id]),
                wait=True,
            )
        except Exception as exc:
            return QdrantMutationResult(
                availability=QdrantAvailability.UNAVAILABLE,
                succeeded=False,
                point_id=point_id,
                reason=self._unavailable_reason(exc),
            )
        return QdrantMutationResult(
            availability=QdrantAvailability.AVAILABLE,
            succeeded=True,
            point_id=point_id,
        )

    def vector_search(
        self,
        *,
        vector: Sequence[float],
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        evidence_type: str | None = None,
        machine_type: str | None = None,
        model: str | None = None,
        site: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        top_k: int,
        score_threshold: float | None = None,
    ) -> QdrantSearchResult:
        values = self._validated_vector(vector)
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        query_filter = self._build_filter(
            machine_id=machine_id,
            component_id=component_id,
            evidence_type=evidence_type,
            machine_type=machine_type,
            model=model,
            site=site,
            start=start,
            end=end,
        )

        started = perf_counter()
        try:
            kwargs: dict[str, Any] = {
                "collection_name": self._collection_name,
                "query": values,
                "limit": top_k,
                "with_payload": True,
                "with_vectors": False,
            }
            if query_filter is not None:
                kwargs["query_filter"] = query_filter
            if score_threshold is not None:
                kwargs["score_threshold"] = float(score_threshold)
            response = self._client.query_points(**kwargs)
            points = getattr(response, "points", response) or ()
        except Exception as exc:
            self._observability.record_qdrant_search(
                latency_ms=(perf_counter() - started) * 1000.0, succeeded=False
            )
            self._observability.record_qdrant_connectivity_failure()
            self._observability.record_capability(
                "qdrant_semantic", CapabilityStatus.UNAVAILABLE, "qdrant_search_failed"
            )
            return QdrantSearchResult(
                availability=QdrantAvailability.UNAVAILABLE,
                hits=(),
                reason=self._unavailable_reason(exc),
            )
        self._observability.record_qdrant_search(
            latency_ms=(perf_counter() - started) * 1000.0, succeeded=True
        )
        self._observability.record_capability(
            "qdrant_semantic", CapabilityStatus.AVAILABLE, "search_succeeded"
        )

        hits: list[SemanticIndexHit] = []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            evidence_id = self._payload_uuid(payload, "evidence_id")
            score = getattr(point, "score", None)
            if evidence_id is None or score is None:
                continue
            try:
                score_value = float(score)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(score_value):
                continue
            hits.append(SemanticIndexHit(evidence_id=evidence_id, score=score_value))
        return QdrantSearchResult(
            availability=QdrantAvailability.AVAILABLE,
            hits=tuple(hits),
        )

    def metadata_search(
        self,
        *,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        evidence_type: str | None = None,
        machine_type: str | None = None,
        model: str | None = None,
        site: str | None = None,
        limit: int = 100,
        offset: object | None = None,
    ) -> QdrantMetadataSearchResult:
        if limit <= 0:
            raise ValueError("limit must be positive")
        scroll_filter = self._build_filter(
            machine_id=machine_id,
            component_id=component_id,
            evidence_type=evidence_type,
            machine_type=machine_type,
            model=model,
            site=site,
        )
        try:
            kwargs: dict[str, Any] = {
                "collection_name": self._collection_name,
                "limit": limit,
                "with_payload": True,
                "with_vectors": False,
            }
            if scroll_filter is not None:
                kwargs["scroll_filter"] = scroll_filter
            if offset is not None:
                kwargs["offset"] = offset
            records, next_offset = self._client.scroll(**kwargs)
        except Exception as exc:
            return QdrantMetadataSearchResult(
                availability=QdrantAvailability.UNAVAILABLE,
                points=(),
                reason=self._unavailable_reason(exc),
            )

        points: list[QdrantPointMetadata] = []
        for record in records or ():
            payload = getattr(record, "payload", None) or {}
            evidence_id = self._payload_uuid(payload, "evidence_id")
            machine_uuid = self._payload_uuid(payload, "machine_id")
            evidence_type_value = payload.get("evidence_type")
            if evidence_id is None or machine_uuid is None or not isinstance(
                evidence_type_value, str
            ):
                continue
            component_uuid = self._payload_uuid(payload, "component_id")
            points.append(
                QdrantPointMetadata(
                    point_id=str(getattr(record, "id", self.point_id_for_evidence(evidence_id))),
                    evidence_id=evidence_id,
                    machine_id=machine_uuid,
                    component_id=component_uuid,
                    evidence_type=evidence_type_value,
                )
            )
        return QdrantMetadataSearchResult(
            availability=QdrantAvailability.AVAILABLE,
            points=tuple(points),
            next_offset=next_offset,
        )

    # ---- Compatibility with the existing provider-neutral SemanticIndex ----

    def upsert_evidence(
        self,
        *,
        evidence_id: UUID,
        machine_id: UUID,
        component_id: UUID | None,
        evidence_type: str,
        vector: Sequence[float],
    ) -> None:
        result = self.upsert_vector(
            evidence_id=evidence_id,
            machine_id=machine_id,
            component_id=component_id,
            evidence_type=evidence_type,
            vector=vector,
        )
        if result.availability is QdrantAvailability.UNAVAILABLE:
            raise QdrantUnavailableError(result.reason or "qdrant_unavailable")

    def search(
        self,
        *,
        vector: Sequence[float],
        machine_id: UUID,
        component_id: UUID | None,
        top_k: int,
        min_similarity: float | None,
    ) -> Sequence[SemanticIndexHit]:
        result = self.vector_search(
            vector=vector,
            machine_id=machine_id,
            component_id=component_id,
            top_k=top_k,
            score_threshold=min_similarity,
        )
        if result.availability is QdrantAvailability.UNAVAILABLE:
            raise QdrantUnavailableError(result.reason or "qdrant_unavailable")
        return result.hits

    def require_compatible_collection(self, *, vector_size: int) -> None:
        """Optional strict wrapper useful to callers that require readiness."""

        result = self.validate_collection(vector_size=vector_size)
        if result.availability is QdrantAvailability.UNAVAILABLE:
            raise QdrantUnavailableError(result.reason or "qdrant_unavailable")
        if not result.compatible:
            raise QdrantCollectionCompatibilityError(
                result.reason or "qdrant_collection_incompatible"
            )

    def _build_filter(
        self,
        *,
        machine_id: UUID | None,
        component_id: UUID | None,
        evidence_type: str | None,
        machine_type: str | None = None,
        model: str | None = None,
        site: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Any | None:
        models = self._models()
        conditions: list[Any] = []
        if machine_id is not None:
            conditions.append(
                models.FieldCondition(
                    key="machine_id",
                    match=models.MatchValue(value=str(machine_id)),
                )
            )
        if component_id is not None:
            conditions.append(
                models.FieldCondition(
                    key="component_id",
                    match=models.MatchValue(value=str(component_id)),
                )
            )
        if evidence_type is not None:
            evidence_type = evidence_type.strip()
            if not evidence_type:
                raise ValueError("evidence_type filter must not be blank")
            conditions.append(
                models.FieldCondition(
                    key="evidence_type",
                    match=models.MatchValue(value=evidence_type),
                )
            )
        for key, value in (("machine_type", machine_type), ("model", model), ("site", site)):
            if value is not None:
                value = value.strip()
                if not value:
                    raise ValueError(f"{key} filter must not be blank")
                conditions.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                )
        if start is not None or end is not None:
            conditions.append(
                models.FieldCondition(
                    key="original_timestamp",
                    range=models.DatetimeRange(
                        gte=self._rfc3339(start) if start is not None else None,
                        lte=self._rfc3339(end) if end is not None else None,
                    ),
                )
            )
        return models.Filter(must=conditions) if conditions else None

    def _ensure_filter_indexes(self) -> None:
        """Create indexes for derived fleet-filter metadata when supported."""

        create_index = getattr(self._client, "create_payload_index", None)
        if not callable(create_index):
            return
        models = self._models()
        schema_type = getattr(models, "PayloadSchemaType", None)
        if schema_type is None:
            return
        existing: set[str] = set()
        try:
            info = self._client.get_collection(collection_name=self._collection_name)
            existing = set((getattr(info, "payload_schema", None) or {}).keys())
        except Exception:
            existing = set()
        fields = {
            "evidence_id": schema_type.KEYWORD,
            "machine_id": schema_type.KEYWORD,
            "component_id": schema_type.KEYWORD,
            "incident_id": schema_type.KEYWORD,
            "session_id": schema_type.KEYWORD,
            "evidence_type": schema_type.KEYWORD,
            "machine_type": schema_type.KEYWORD,
            "model": schema_type.KEYWORD,
            "site": schema_type.KEYWORD,
            "original_timestamp": schema_type.DATETIME,
        }
        for field_name, field_schema in fields.items():
            if field_name in existing:
                continue
            create_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=field_schema,
                wait=True,
            )

    def _models(self) -> Any:
        if self._models_module is not None:
            return self._models_module
        from qdrant_client.http import models  # type: ignore[import-not-found]

        return models

    def _qdrant_distance_model(self, models: Any) -> Any:
        return getattr(models.Distance, _DISTANCE_MODEL_NAMES[self._distance])

    @staticmethod
    def _validate_vector_size(vector_size: int) -> int:
        if isinstance(vector_size, bool):
            raise ValueError("vector_size must be a positive integer")
        try:
            size = int(vector_size)
        except (TypeError, ValueError) as exc:
            raise ValueError("vector_size must be a positive integer") from exc
        if size <= 0 or size != vector_size:
            raise ValueError("vector_size must be a positive integer")
        return size

    @staticmethod
    def _validated_vector(vector: Sequence[float]) -> list[float]:
        if isinstance(vector, (str, bytes, bytearray)):
            raise ValueError("vector must be a numeric sequence")
        values = [float(value) for value in vector]
        if not values:
            raise ValueError("vector must not be empty")
        if any(not math.isfinite(value) for value in values):
            raise ValueError("vector values must be finite")
        return values

    @staticmethod
    def _payload_uuid(payload: dict[str, Any], key: str) -> UUID | None:
        value = payload.get(key)
        if value is None:
            return None
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _rfc3339(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _unavailable_reason(exc: Exception) -> str:
        return f"qdrant_unavailable:{type(exc).__name__}"

    def _collection_unavailable(
        self, vector_size: int, exc: Exception
    ) -> QdrantCollectionResult:
        return QdrantCollectionResult(
            availability=QdrantAvailability.UNAVAILABLE,
            collection_name=self._collection_name,
            exists=False,
            compatible=None,
            expected_vector_size=vector_size,
            actual_vector_size=None,
            expected_distance=self._distance,
            actual_distance=None,
            reason=self._unavailable_reason(exc),
        )

    @staticmethod
    def _normalize_distance(value: Any) -> QdrantDistance | None:
        if value is None:
            return None
        raw = getattr(value, "value", value)
        normalized = str(raw).strip().lower()
        aliases = {
            "cosine": QdrantDistance.COSINE,
            "distance.cosine": QdrantDistance.COSINE,
            "dot": QdrantDistance.DOT,
            "distance.dot": QdrantDistance.DOT,
            "euclid": QdrantDistance.EUCLID,
            "euclidean": QdrantDistance.EUCLID,
            "distance.euclid": QdrantDistance.EUCLID,
            "manhattan": QdrantDistance.MANHATTAN,
            "distance.manhattan": QdrantDistance.MANHATTAN,
        }
        return aliases.get(normalized)


class QdrantClientSemanticIndex(QdrantService):
    """Backward-compatible class name for the concrete Qdrant service."""


__all__ = ["QdrantClientSemanticIndex", "QdrantService"]
