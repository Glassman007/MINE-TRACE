from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.settings import Settings
from app.integrations.qdrant import (
    QdrantAvailability,
    QdrantDistance,
    QdrantService,
    QdrantUnavailableError,
)


class FakeDistance:
    COSINE = "Cosine"
    DOT = "Dot"
    EUCLID = "Euclid"
    MANHATTAN = "Manhattan"


class FakeVectorParams:
    def __init__(self, *, size: int, distance: object) -> None:
        self.size = size
        self.distance = distance


class FakePointStruct:
    def __init__(self, *, id: str, vector: list[float], payload: dict[str, str]) -> None:
        self.id = id
        self.vector = vector
        self.payload = payload


class FakeMatchValue:
    def __init__(self, *, value: str) -> None:
        self.value = value


class FakeFieldCondition:
    def __init__(self, *, key: str, match: FakeMatchValue) -> None:
        self.key = key
        self.match = match


class FakeFilter:
    def __init__(self, *, must: list[FakeFieldCondition]) -> None:
        self.must = must


class FakePointIdsList:
    def __init__(self, *, points: list[str]) -> None:
        self.points = points


class FakeModels:
    Distance = FakeDistance
    VectorParams = FakeVectorParams
    PointStruct = FakePointStruct
    MatchValue = FakeMatchValue
    FieldCondition = FakeFieldCondition
    Filter = FakeFilter
    PointIdsList = FakePointIdsList


class FakeQdrantClient:
    def __init__(self) -> None:
        self.available = True
        self.collection_exists_value = False
        self.collection_vector_size = 3
        self.collection_distance: object = FakeDistance.COSINE
        self.collection_names = ["other_collection"]
        self.created: list[dict[str, object]] = []
        self.deleted_collections: list[str] = []
        self.upserts: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []
        self.queries: list[dict[str, object]] = []
        self.scrolls: list[dict[str, object]] = []
        self.query_points_result: list[object] = []
        self.scroll_result: tuple[list[object], object | None] = ([], None)

    def _check(self) -> None:
        if not self.available:
            raise ConnectionError("qdrant offline")

    def get_collections(self) -> object:
        self._check()
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in self.collection_names]
        )

    def collection_exists(self, *, collection_name: str) -> bool:
        self._check()
        return self.collection_exists_value

    def create_collection(self, **kwargs: object) -> None:
        self._check()
        self.created.append(kwargs)
        self.collection_exists_value = True
        vector_config = kwargs["vectors_config"]
        self.collection_vector_size = vector_config.size
        self.collection_distance = vector_config.distance

    def delete_collection(self, *, collection_name: str) -> None:
        self._check()
        self.deleted_collections.append(collection_name)
        self.collection_exists_value = False

    def get_collection(self, *, collection_name: str) -> object:
        self._check()
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=FakeVectorParams(
                        size=self.collection_vector_size,
                        distance=self.collection_distance,
                    )
                )
            )
        )

    def upsert(self, **kwargs: object) -> None:
        self._check()
        self.upserts.append(kwargs)

    def delete(self, **kwargs: object) -> None:
        self._check()
        self.deletes.append(kwargs)

    def query_points(self, **kwargs: object) -> object:
        self._check()
        self.queries.append(kwargs)
        return SimpleNamespace(points=self.query_points_result)

    def scroll(self, **kwargs: object) -> tuple[list[object], object | None]:
        self._check()
        self.scrolls.append(kwargs)
        return self.scroll_result


def service(client: FakeQdrantClient, *, distance: QdrantDistance = QdrantDistance.COSINE) -> QdrantService:
    return QdrantService(
        collection_name="mine_trace_evidence",
        distance=distance,
        client=client,
        models_module=FakeModels,
    )


def filter_values(filter_obj: FakeFilter) -> dict[str, str]:
    return {condition.key: condition.match.value for condition in filter_obj.must}


def test_connectivity_and_collection_discovery_are_typed() -> None:
    client = FakeQdrantClient()
    client.collection_names = ["z", "mine_trace_evidence", "a"]
    qdrant = service(client)

    assert qdrant.connectivity().availability is QdrantAvailability.AVAILABLE
    discovered = qdrant.discover_collections()
    assert discovered.availability is QdrantAvailability.AVAILABLE
    assert discovered.collections == ("a", "mine_trace_evidence", "z")

    client.available = False
    unavailable = qdrant.discover_collections()
    assert unavailable.availability is QdrantAvailability.UNAVAILABLE
    assert unavailable.collections == ()


def test_collection_initialization_uses_runtime_vector_size_and_central_distance() -> None:
    client = FakeQdrantClient()
    qdrant = service(client)

    result = qdrant.initialize_collection(vector_size=17)

    assert result.availability is QdrantAvailability.AVAILABLE
    assert result.created is True
    assert result.compatible is True
    assert result.actual_vector_size == 17
    assert result.actual_distance is QdrantDistance.COSINE
    assert client.created[0]["collection_name"] == "mine_trace_evidence"
    params = client.created[0]["vectors_config"]
    assert params.size == 17
    assert params.distance == FakeDistance.COSINE


def test_collection_compatibility_validates_dimension_and_distance() -> None:
    client = FakeQdrantClient()
    client.collection_exists_value = True
    client.collection_vector_size = 6
    client.collection_distance = FakeDistance.COSINE
    qdrant = service(client)

    ok = qdrant.validate_collection(vector_size=6)
    assert ok.compatible is True

    wrong_dimension = qdrant.validate_collection(vector_size=7)
    assert wrong_dimension.compatible is False
    assert "vector_size_mismatch" in (wrong_dimension.reason or "")

    wrong_distance = service(client, distance=QdrantDistance.DOT).validate_collection(vector_size=6)
    assert wrong_distance.compatible is False
    assert "distance_mismatch" in (wrong_distance.reason or "")


def test_upsert_uses_deterministic_evidence_uuid_and_minimal_payload() -> None:
    client = FakeQdrantClient()
    qdrant = service(client)
    evidence_id = uuid4()
    machine_id = uuid4()
    component_id = uuid4()

    first = qdrant.upsert_vector(
        evidence_id=evidence_id,
        machine_id=machine_id,
        component_id=component_id,
        evidence_type="HUMAN_OBSERVATION",
        vector=[0.1, 0.2, 0.3],
    )
    second = qdrant.upsert_vector(
        evidence_id=evidence_id,
        machine_id=machine_id,
        component_id=component_id,
        evidence_type="HUMAN_OBSERVATION",
        vector=[0.4, 0.5, 0.6],
    )

    assert first.succeeded is True
    assert second.point_id == first.point_id == str(evidence_id)
    assert len(client.upserts) == 2
    for call in client.upserts:
        point = call["points"][0]
        assert point.id == str(evidence_id)
        assert point.payload == {
            "evidence_id": str(evidence_id),
            "machine_id": str(machine_id),
            "component_id": str(component_id),
            "evidence_type": "HUMAN_OBSERVATION",
        }
        assert "provenance" not in point.payload
        assert "incident_state" not in point.payload
        assert "audit_history" not in point.payload


def test_upsert_omits_component_key_when_component_is_absent() -> None:
    client = FakeQdrantClient()
    qdrant = service(client)
    qdrant.upsert_vector(
        evidence_id=uuid4(),
        machine_id=uuid4(),
        component_id=None,
        evidence_type="MACHINE_EVENT",
        vector=[0.1, 0.2],
    )
    point = client.upserts[0]["points"][0]
    assert "component_id" not in point.payload


def test_vector_delete_removes_only_deterministic_derived_point() -> None:
    client = FakeQdrantClient()
    qdrant = service(client)
    evidence_id = uuid4()

    result = qdrant.delete_vector(evidence_id=evidence_id)

    assert result.succeeded is True
    selector = client.deletes[0]["points_selector"]
    assert selector.points == [str(evidence_id)]


def test_vector_search_builds_metadata_filter_and_returns_only_valid_ids() -> None:
    client = FakeQdrantClient()
    qdrant = service(client)
    machine_id = uuid4()
    component_id = uuid4()
    hit_id = uuid4()
    client.query_points_result = [
        SimpleNamespace(payload={"evidence_id": str(hit_id)}, score=0.812),
        SimpleNamespace(payload={"evidence_id": "not-a-uuid"}, score=0.999),
    ]

    result = qdrant.vector_search(
        vector=[0.2, 0.3],
        machine_id=machine_id,
        component_id=component_id,
        evidence_type="TECHNICIAN_NOTE",
        top_k=5,
        score_threshold=0.6,
    )

    assert result.availability is QdrantAvailability.AVAILABLE
    assert [(hit.evidence_id, hit.score) for hit in result.hits] == [(hit_id, 0.812)]
    query = client.queries[0]
    assert query["query"] == [0.2, 0.3]
    assert query["limit"] == 5
    assert query["score_threshold"] == 0.6
    assert filter_values(query["query_filter"]) == {
        "machine_id": str(machine_id),
        "component_id": str(component_id),
        "evidence_type": "TECHNICIAN_NOTE",
    }


def test_metadata_filter_search_returns_only_minimal_metadata() -> None:
    client = FakeQdrantClient()
    qdrant = service(client)
    evidence_id = uuid4()
    machine_id = uuid4()
    component_id = uuid4()
    client.scroll_result = (
        [
            SimpleNamespace(
                id=str(evidence_id),
                payload={
                    "evidence_id": str(evidence_id),
                    "machine_id": str(machine_id),
                    "component_id": str(component_id),
                    "evidence_type": "HUMAN_OBSERVATION",
                    "unexpected": "ignored",
                },
            )
        ],
        "next-token",
    )

    result = qdrant.metadata_search(machine_id=machine_id, evidence_type="HUMAN_OBSERVATION")

    assert result.availability is QdrantAvailability.AVAILABLE
    assert len(result.points) == 1
    point = result.points[0]
    assert point.evidence_id == evidence_id
    assert point.machine_id == machine_id
    assert point.component_id == component_id
    assert point.evidence_type == "HUMAN_OBSERVATION"
    assert result.next_offset == "next-token"
    scroll = client.scrolls[0]
    assert scroll["with_vectors"] is False
    assert filter_values(scroll["scroll_filter"]) == {
        "machine_id": str(machine_id),
        "evidence_type": "HUMAN_OBSERVATION",
    }


def test_qdrant_unavailable_returns_typed_empty_states_not_fake_results() -> None:
    client = FakeQdrantClient()
    client.available = False
    qdrant = service(client)

    assert qdrant.connectivity().availability is QdrantAvailability.UNAVAILABLE

    collection = qdrant.initialize_collection(vector_size=8)
    assert collection.availability is QdrantAvailability.UNAVAILABLE
    assert collection.compatible is None

    upsert = qdrant.upsert_vector(
        evidence_id=uuid4(),
        machine_id=uuid4(),
        component_id=None,
        evidence_type="TEST",
        vector=[0.1, 0.2],
    )
    assert upsert.availability is QdrantAvailability.UNAVAILABLE
    assert upsert.succeeded is False

    search = qdrant.vector_search(vector=[0.1, 0.2], top_k=5)
    assert search.availability is QdrantAvailability.UNAVAILABLE
    assert search.hits == ()

    metadata = qdrant.metadata_search(limit=5)
    assert metadata.availability is QdrantAvailability.UNAVAILABLE
    assert metadata.points == ()


def test_legacy_semantic_index_wrapper_converts_unavailability_to_typed_exception() -> None:
    client = FakeQdrantClient()
    client.available = False
    qdrant = service(client)

    with pytest.raises(QdrantUnavailableError):
        qdrant.search(
            vector=[0.1, 0.2],
            machine_id=uuid4(),
            component_id=None,
            top_k=5,
            min_similarity=None,
        )


def test_from_settings_uses_central_distance_and_collection_configuration() -> None:
    client = FakeQdrantClient()
    settings = Settings(
        environment="test",
        qdrant_collection="semantic_test",
        qdrant_distance="dot",
    )

    qdrant = QdrantService.from_settings(
        settings,
        client=client,
        models_module=FakeModels,
    )

    assert qdrant.collection_name == "semantic_test"
    assert qdrant.distance is QdrantDistance.DOT


def test_qdrant_score_is_only_a_raw_ranking_value_contract() -> None:
    from app.integrations.qdrant.types import QdrantSearchResult

    assert "not a confidence" in (QdrantSearchResult.__doc__ or "").lower()


def test_recreate_collection_replaces_only_derived_collection() -> None:
    client = FakeQdrantClient()
    client.collection_exists_value = True
    qdrant = service(client)

    result = qdrant.recreate_collection(vector_size=11)

    assert result.availability is QdrantAvailability.AVAILABLE
    assert result.compatible is True
    assert result.actual_vector_size == 11
    assert client.deleted_collections == ["mine_trace_evidence"]
    assert len(client.created) == 1


def test_delete_collection_is_idempotent_for_missing_derived_collection() -> None:
    client = FakeQdrantClient()
    qdrant = service(client)

    result = qdrant.delete_collection()

    assert result.availability is QdrantAvailability.AVAILABLE
    assert result.succeeded is True
    assert client.deleted_collections == []


def test_upsert_includes_optional_session_and_unambiguous_incident_metadata() -> None:
    client = FakeQdrantClient()
    qdrant = service(client)
    evidence_id, machine_id, component_id, session_id, incident_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    result = qdrant.upsert_vector(
        evidence_id=evidence_id,
        machine_id=machine_id,
        component_id=component_id,
        session_id=session_id,
        incident_id=incident_id,
        evidence_type="HUMAN_OBSERVATION",
        vector=[0.1, 0.2, 0.3],
    )
    assert result.succeeded is True
    payload = client.upserts[0]["points"][0].payload
    assert payload["session_id"] == str(session_id)
    assert payload["incident_id"] == str(incident_id)
    assert "canonical_payload" not in payload
    assert "sync_envelope" not in payload
