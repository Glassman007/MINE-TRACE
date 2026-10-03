from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings
from app.db.base import Base
from app.db.session import create_database_engine, get_db_session
from app.main import app
from app.models import MachineRecord


def _client(tmp_path: Path, *, semantic_enabled: bool = False):
    machine_id = uuid4()
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        sqlite_wal_enabled=False,
        local_machine_id=machine_id,
        semantic_search_enabled=semantic_enabled,
        qdrant_url="http://127.0.0.1:6333" if semantic_enabled else None,
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))

    def db_override() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = db_override
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), engine


def test_return_to_service_api_exposes_auditable_backend_policy(tmp_path: Path) -> None:
    client, engine = _client(tmp_path)
    try:
        with client:
            response = client.get("/api/v1/return-to-service")
        assert response.status_code == 200
        payload = response.json()
        assert payload["state"] == "CLEARED"
        assert payload["policy_identifier"] == "local.return-to-service.v1"
        assert payload["policy_revision"] == 1
        assert payload["blocking_reasons"] == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_semantic_search_api_returns_typed_disabled_state_without_loading_model(tmp_path: Path) -> None:
    client, engine = _client(tmp_path, semantic_enabled=False)
    try:
        with client:
            response = client.post("/api/v1/semantic-search", json={"query": "hydraulic pump noise"})
        assert response.status_code == 200
        assert response.json() == {
            "available": False,
            "classification": "Semantic",
            "results": [],
            "failure": "SEMANTIC_SEARCH_DISABLED",
            "reason": "semantic search is disabled",
        }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
