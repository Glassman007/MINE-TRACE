from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings
from app.db.base import Base
from app.db.session import create_database_engine, get_db_session
from app.main import app
from app.models import MachineRecord

MACHINE_ID = UUID("00000000-0000-0000-0000-000000000011")


@contextmanager
def _client(tmp_path: Path) -> Generator[TestClient, None, None]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'local11.db'}",
        sqlite_wal_enabled=False,
        local_machine_id=MACHINE_ID,
        # Optional integrations intentionally unavailable.
        semantic_search_enabled=True,
        qdrant_url=None,
        qdrant_location="./missing-qdrant",
        ai_enabled=False,
        global_backend_base_url=None,
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    with factory.begin() as session:
        session.add(MachineRecord(id=MACHINE_ID, display_name="Configured Local Machine"))

    def override_db() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_prompt_11_required_local_routes_are_documented(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        paths = client.get("/openapi.json").json()["paths"]
        required = {
            "/api/v1/sessions",
            "/api/v1/sessions/active",
            "/api/v1/sessions/{session_id}",
            "/api/v1/sessions/{session_id}/report",
            "/api/v1/semantic-search",
            "/api/v1/return-to-service",
            "/api/v1/sync/status",
            "/api/v1/machines/current",
            "/api/v1/machines/current/components",
        }
        assert required <= set(paths)


def test_core_health_ignores_missing_optional_semantic_and_ai_capabilities(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}
