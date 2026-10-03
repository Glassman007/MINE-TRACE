from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.api.health import health
from app.core.settings import Settings
from app.db.session import create_database_engine


class FakeSession:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, statement: Any) -> None:
        self.executed.append(str(statement))


def test_global_settings_are_postgresql_first_and_have_no_sqlite_runtime_controls() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:pass@db.example.test:5432/mine_trace",
        db_pool_size=7,
        db_max_overflow=11,
        db_pool_timeout_seconds=9,
        db_pool_recycle_seconds=600,
    )

    assert settings.database_url.startswith("postgresql+")
    assert settings.db_pool_size == 7
    assert settings.db_max_overflow == 11
    assert not hasattr(settings, "sqlite_wal_enabled")
    assert not hasattr(settings, "sqlite_busy_timeout_ms")
    assert not hasattr(settings, "incident_linking_window_minutes")
    assert not hasattr(settings, "verification_window_minutes")


def test_non_postgresql_canonical_database_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must use PostgreSQL"):
        Settings(database_url="sqlite:///mine_trace.db")


def test_engine_configuration_uses_postgresql_pool_controls_without_sqlite_args() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:pass@db.example.test:5432/mine_trace",
        db_pool_size=8,
        db_max_overflow=13,
        db_pool_timeout_seconds=17,
        db_pool_recycle_seconds=901,
    )
    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_engine_factory(url: str, **kwargs: Any):
        captured["url"] = url
        captured.update(kwargs)
        return sentinel

    result = create_database_engine(settings, engine_factory=fake_engine_factory)  # type: ignore[arg-type]

    assert result is sentinel
    assert captured == {
        "url": settings.database_url,
        "pool_pre_ping": True,
        "pool_size": 8,
        "max_overflow": 13,
        "pool_timeout": 17.0,
        "pool_recycle": 901,
    }
    assert "connect_args" not in captured


def test_health_probe_reports_canonical_postgresql_role() -> None:
    session = FakeSession()
    response = health(session=session)  # type: ignore[arg-type]

    assert session.executed == ["SELECT 1"]
    assert response.status == "ok"
    assert response.database == "ok"
    assert response.database_role == "canonical_postgresql"
