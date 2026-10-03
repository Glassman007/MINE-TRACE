from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.capabilities import (
    CapabilityStatus,
    ai_configuration_state,
    semantic_configuration_state,
)
from app.core.settings import Settings


def test_business_thresholds_are_typed_and_validated() -> None:
    settings = Settings(
        semantic_top_k=7,
        semantic_score_threshold=0.8,
        evidence_bundle_limit=50,
    )

    assert settings.semantic_top_k == 7
    assert settings.semantic_score_threshold == 0.8
    assert settings.evidence_bundle_limit == 50


def test_semantic_defaults_do_not_invent_similarity_cutoff() -> None:
    settings = Settings()
    assert settings.semantic_top_k == 5
    assert settings.semantic_score_threshold is None


def test_ml_ai_configuration_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINE_TRACE_SEMANTIC_SEARCH_ENABLED", "true")
    monkeypatch.setenv("MINE_TRACE_QDRANT_URL", "https://qdrant.example.test")
    monkeypatch.setenv("MINE_TRACE_QDRANT_API_KEY", "qdrant-test-secret")
    monkeypatch.setenv("MINE_TRACE_QDRANT_COLLECTION", "mine_trace_semantic")
    monkeypatch.setenv("MINE_TRACE_QDRANT_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setenv("MINE_TRACE_EMBEDDING_PROVIDER", "provider-from-env")
    monkeypatch.setenv("MINE_TRACE_EMBEDDING_MODEL", "embedding-model-from-env")
    monkeypatch.setenv("MINE_TRACE_EMBEDDING_API_KEY", "embedding-test-secret")
    monkeypatch.setenv("MINE_TRACE_SEMANTIC_TOP_K", "9")
    monkeypatch.setenv("MINE_TRACE_SEMANTIC_SCORE_THRESHOLD", "0.72")
    monkeypatch.setenv("MINE_TRACE_AI_ENABLED", "true")
    monkeypatch.setenv("MINE_TRACE_AI_PROVIDER", "ai-provider-from-env")
    monkeypatch.setenv("MINE_TRACE_AI_MODEL", "ai-model-from-env")
    monkeypatch.setenv("MINE_TRACE_AI_API_KEY", "ai-test-secret")
    monkeypatch.setenv("MINE_TRACE_AI_TIMEOUT_SECONDS", "18")

    settings = Settings(_env_file=None)

    assert settings.semantic_search_enabled is True
    assert settings.qdrant_url == "https://qdrant.example.test"
    assert settings.qdrant_api_key is not None
    assert settings.qdrant_api_key.get_secret_value() == "qdrant-test-secret"
    assert settings.qdrant_collection == "mine_trace_semantic"
    assert settings.qdrant_timeout_seconds == 4.5
    assert settings.embedding_provider == "provider-from-env"
    assert settings.embedding_model == "embedding-model-from-env"
    assert settings.embedding_api_key is not None
    assert settings.embedding_api_key.get_secret_value() == "embedding-test-secret"
    assert settings.semantic_top_k == 9
    assert settings.semantic_score_threshold == 0.72
    assert settings.ai_enabled is True
    assert settings.ai_provider == "ai-provider-from-env"
    assert settings.ai_model == "ai-model-from-env"
    assert settings.ai_api_key is not None
    assert settings.ai_api_key.get_secret_value() == "ai-test-secret"
    assert settings.ai_timeout_seconds == 18


def test_enabled_semantic_search_rejects_invalid_qdrant_url() -> None:
    with pytest.raises(ValidationError):
        Settings(
            semantic_search_enabled=True,
            qdrant_url="not-a-url",
            embedding_provider="provider",
            embedding_model="model",
        )


def test_missing_optional_integration_configuration_is_a_status_not_startup_error() -> None:
    semantic = semantic_configuration_state(Settings(semantic_search_enabled=True))
    ai = ai_configuration_state(Settings(ai_enabled=True))

    assert semantic.status is CapabilityStatus.UNAVAILABLE
    assert ai.status is CapabilityStatus.UNAVAILABLE


def test_disabled_capabilities_report_disabled() -> None:
    settings = Settings(semantic_search_enabled=False, ai_enabled=False)

    assert semantic_configuration_state(settings).status is CapabilityStatus.DISABLED
    assert ai_configuration_state(settings).status is CapabilityStatus.DISABLED


def test_selected_openai_provider_requires_key_for_available_capability() -> None:
    settings = Settings(
        ai_enabled=True,
        ai_provider="openai",
        ai_model="configured-model",
        ai_api_key=None,
    )

    state = ai_configuration_state(settings)
    assert state.status is CapabilityStatus.UNAVAILABLE
    assert state.reason is not None
    assert "ai_api_key" in state.reason


def test_ai_api_key_is_not_universally_required() -> None:
    settings = Settings(
        ai_enabled=True,
        ai_provider="local-or-workload-identity-provider",
        ai_model="configured-model",
        ai_api_key=None,
    )

    assert ai_configuration_state(settings).status is CapabilityStatus.UNAVAILABLE


def test_secret_values_are_redacted_in_settings_repr() -> None:
    settings = Settings(
        qdrant_api_key="fake-q",
        embedding_api_key="fake-e",
        ai_api_key="fake-a",
    )

    rendered = repr(settings)
    assert "fake-q" not in rendered
    assert "fake-e" not in rendered
    assert "fake-a" not in rendered
    assert "**********" in rendered


def test_env_example_contains_placeholders_only_for_secrets() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    env_example = (repository_root / ".env.example").read_text(encoding="utf-8")
    gitignore = (repository_root / ".gitignore").read_text(encoding="utf-8")

    assert "\n.env\n" in f"\n{gitignore.strip()}\n"
    assert "MINE_TRACE_QDRANT_API_KEY=\n" in env_example
    assert "MINE_TRACE_EMBEDDING_API_KEY=\n" in env_example
    assert "MINE_TRACE_AI_API_KEY=\n" in env_example
