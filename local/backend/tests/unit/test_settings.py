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
    monkeypatch.setenv("MINE_TRACE_GROQ_API_KEY", "ai-test-secret")
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
    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "ai-test-secret"
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


def test_selected_groq_provider_requires_key_for_available_capability() -> None:
    settings = Settings(
        ai_enabled=True,
        ai_provider="groq",
        ai_model="configured-model",
        groq_api_key=None,
    )

    state = ai_configuration_state(settings)
    assert state.status is CapabilityStatus.UNAVAILABLE
    assert state.reason is not None
    assert "groq_api_key" in state.reason


def test_groq_api_key_is_not_universally_required() -> None:
    settings = Settings(
        ai_enabled=True,
        ai_provider="local-or-workload-identity-provider",
        ai_model="configured-model",
        groq_api_key=None,
    )

    assert ai_configuration_state(settings).status is CapabilityStatus.UNAVAILABLE


def test_secret_values_are_redacted_in_settings_repr() -> None:
    settings = Settings(
        qdrant_api_key="fake-q",
        embedding_api_key="fake-e",
        groq_api_key="fake-a",
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
    assert "MINE_TRACE_GROQ_API_KEY=\n" in env_example


def test_local_node_configuration_does_not_require_cloud_credentials() -> None:
    settings = Settings(
        local_machine_id="11111111-1111-1111-1111-111111111111",
        qdrant_url="http://127.0.0.1:6333",
        qdrant_collection="mine_trace_local",
        embedding_provider="local-offline-placeholder",
        embedding_model="cached-model",
        embedding_vector_dimension=384,
        global_backend_base_url="https://central.example.test",
    )

    assert settings.qdrant_api_key is None
    assert settings.embedding_api_key is None
    assert settings.groq_api_key is None
    assert settings.ai_enabled is False
    assert str(settings.local_machine_id) == "11111111-1111-1111-1111-111111111111"


def test_embedding_vector_dimension_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(embedding_vector_dimension=0)


def test_optional_transport_urls_are_validated_when_supplied() -> None:
    with pytest.raises(ValidationError):
        Settings(qdrant_url="not-a-url")
    with pytest.raises(ValidationError):
        Settings(global_backend_base_url="central-backend")


def test_local_qdrant_location_and_url_are_distinct_configuration_modes() -> None:
    local_path = Settings(qdrant_location="./qdrant-data")
    local_url = Settings(qdrant_url="http://127.0.0.1:6333")

    assert local_path.qdrant_location == "./qdrant-data"
    assert local_path.qdrant_url is None
    assert local_url.qdrant_url == "http://127.0.0.1:6333"
    assert local_url.qdrant_location is None

    with pytest.raises(ValidationError):
        Settings(qdrant_location="./qdrant-data", qdrant_url="http://127.0.0.1:6333")


def test_sync_retry_configuration_is_typed_and_ordered() -> None:
    settings = Settings(
        sync_retry_initial_seconds=2,
        sync_retry_max_seconds=30,
        sync_retry_max_attempts=5,
    )
    assert settings.sync_retry_initial_seconds == 2
    assert settings.sync_retry_max_seconds == 30
    assert settings.sync_retry_max_attempts == 5

    with pytest.raises(ValidationError):
        Settings(sync_retry_initial_seconds=60, sync_retry_max_seconds=10)


def test_local_identity_and_edge_references_are_not_secret_values() -> None:
    settings = Settings(
        local_node_id="edge-node-a",
        edge_credential_reference="secret-store://mine-trace/edge-credential",
        edge_token_reference="secret-store://mine-trace/token",
        edge_certificate_reference="file-ref://certs/edge.pem",
    )
    assert settings.local_node_id == "edge-node-a"
    assert settings.edge_token_reference == "secret-store://mine-trace/token"


def test_env_example_has_no_committed_local_identity_or_edge_secret_material() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    env_example = (repository_root / ".env.example").read_text(encoding="utf-8")

    assert "MINE_TRACE_LOCAL_MACHINE_ID=\n" in env_example
    assert "MINE_TRACE_LOCAL_NODE_ID=\n" in env_example
    assert "MINE_TRACE_EDGE_CREDENTIAL_REFERENCE=\n" in env_example
    assert "MINE_TRACE_EDGE_TOKEN_REFERENCE=\n" in env_example
    assert "MINE_TRACE_EDGE_CERTIFICATE_REFERENCE=\n" in env_example
    assert "MINE_TRACE_QDRANT_API_KEY=\n" in env_example
    assert "MINE_TRACE_EMBEDDING_PROVIDER=fastembed_local\n" in env_example
    assert "MINE_TRACE_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5\n" in env_example
    assert "MINE_TRACE_EMBEDDING_VECTOR_DIMENSION=384\n" in env_example
    assert "MINE_TRACE_GROQ_API_KEY=\n" in env_example


def test_local_offline_embedding_defaults_are_pinned_and_dimension_locked() -> None:
    settings = Settings()
    assert settings.embedding_provider == "fastembed_local"
    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"
    assert settings.embedding_vector_dimension == 384
    assert settings.embedding_cache_location == "./models/fastembed"

    with pytest.raises(ValidationError):
        Settings(embedding_vector_dimension=768)
    with pytest.raises(ValidationError):
        Settings(embedding_model="some-other-model")
