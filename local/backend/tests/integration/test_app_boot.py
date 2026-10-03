import pytest
from fastapi.testclient import TestClient

import app.core.capabilities as capabilities
import app.main as main_module
from app.core.capabilities import CapabilityStatus
from app.core.settings import Settings


def test_application_starts_cleanly() -> None:
    with TestClient(main_module.app) as client:
        assert client.app is main_module.app


def test_application_boots_with_semantic_search_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(semantic_search_enabled=False),
    )

    with TestClient(main_module.app) as client:
        state = client.app.state.semantic_retrieval_capability
        assert state.status is CapabilityStatus.DISABLED


def test_application_boots_with_ai_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "settings", Settings(ai_enabled=False))

    with TestClient(main_module.app) as client:
        state = client.app.state.ai_capability
        assert state.status is CapabilityStatus.DISABLED


def test_missing_ai_key_does_not_crash_canonical_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            ai_enabled=True,
            ai_provider="local-or-workload-identity-provider",
            ai_model="configured-model",
            groq_api_key=None,
        ),
    )

    with TestClient(main_module.app) as client:
        state = client.app.state.ai_capability
        assert state.status is CapabilityStatus.UNAVAILABLE


def test_unavailable_qdrant_does_not_corrupt_application_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            semantic_search_enabled=True,
            qdrant_url="http://127.0.0.1:6333",
            qdrant_collection="mine_trace_evidence",
            embedding_provider="configured-provider",
            embedding_model="configured-model",
        ),
    )

    def unavailable_probe(_settings: Settings) -> None:
        raise ConnectionError("qdrant unavailable")

    monkeypatch.setattr(capabilities, "probe_qdrant", unavailable_probe)

    with TestClient(main_module.app) as client:
        state = client.app.state.semantic_retrieval_capability
        assert state.status is CapabilityStatus.UNAVAILABLE
        assert state.reason == "qdrant_unavailable"
        assert client.app is main_module.app
