from functools import lru_cache
from typing import Literal
from uuid import UUID

from app.domain.enums import IncidentStatus, VerificationRunResult
from app.contracts.versioning import CURRENT_TRANSPORT_SCHEMA_VERSION, ensure_supported_major

from pydantic import Field, SecretStr, TypeAdapter, AnyHttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration for the MINE-TRACE backend.

    Canonical backend settings are independent from optional semantic/AI
    integrations. Optional integration configuration may be absent without
    making the deterministic backend invalid.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MINE_TRACE_",
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
    )

    app_name: str = "MINE-TRACE Backend"
    environment: Literal["development", "test", "staging", "production"] = "development"
    api_prefix: str = ""
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    demo_mode: bool = False

    database_url: str = "sqlite:///./mine_trace.db"
    sqlite_busy_timeout_ms: int = Field(default=5_000, ge=0)
    sqlite_wal_enabled: bool = True

    # Local-node identity and transport contract. Identity is optional at process
    # startup so migrations/tests and non-node tooling remain usable, but local
    # session operations require an explicitly configured machine.
    local_machine_id: UUID | None = None
    local_node_id: str | None = None
    transport_schema_version: str = Field(
        default=CURRENT_TRANSPORT_SCHEMA_VERSION, pattern=r"^[1-9]\d*\.\d+$"
    )

    incident_linking_window_minutes: int = Field(default=60, gt=0)
    incident_linking_rule_identifier: str = Field(
        default="mvp.same-machine-component-compatible-event-window.v1",
        min_length=1,
    )
    incident_linking_rule_name: str = Field(
        default="MVP deterministic incident linking",
        min_length=1,
    )
    incident_linking_active_statuses: tuple[IncidentStatus, ...] = (
        IncidentStatus.OPEN,
        IncidentStatus.VERIFYING,
        IncidentStatus.RECURRED,
        IncidentStatus.VERIFIED,
    )
    incident_linking_allow_identical_event_type: bool = True
    incident_linking_compatible_event_pairs: dict[str, tuple[str, ...]] = Field(
        default_factory=dict
    )
    incident_correction_rule_identifier: str = Field(
        default="mvp.explicit-incident-correction.v1",
        min_length=1,
    )
    incident_correction_rule_name: str = Field(
        default="MVP explicit incident association correction",
        min_length=1,
    )
    history_lookback_days: int = Field(default=30, gt=0)
    verification_window_minutes: int = Field(default=30, gt=0)
    verification_rule_identifier: str = Field(
        default="mvp.no-event.v1",
        min_length=1,
    )
    verification_rule_name: str = Field(
        default="MVP no-event verification",
        min_length=1,
    )
    evidence_bundle_limit: int = Field(default=100, gt=0)

    # Return-to-service policy. Site-specific blocking mappings are explicit and
    # typed; untyped severity/health/ML signals are intentionally excluded.
    return_to_service_policy_identifier: str = Field(
        default="local.return-to-service.v1", min_length=1
    )
    return_to_service_policy_revision: int = Field(default=1, ge=1)
    return_to_service_do_not_return_incident_statuses: tuple[IncidentStatus, ...] = ()
    return_to_service_verification_required_incident_statuses: tuple[IncidentStatus, ...] = (
        IncidentStatus.VERIFYING,
    )
    return_to_service_do_not_return_verification_results: tuple[VerificationRunResult, ...] = ()
    return_to_service_verification_required_on_pending_run: bool = True

    # Optional derived semantic-memory configuration. Qdrant is never canonical.
    semantic_search_enabled: bool = False
    qdrant_url: str | None = None
    # Optional local embedded/path location. It is configuration only in this
    # phase; the existing Qdrant adapter continues to use URL mode until the
    # later local-semantic implementation prompt.
    qdrant_location: str | None = None
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = Field(default="mine_trace_evidence", min_length=1)
    qdrant_timeout_seconds: float = Field(default=3.0, gt=0.0, le=120.0)
    qdrant_distance: Literal["cosine", "dot", "euclid", "manhattan"] = "cosine"

    embedding_provider: str | None = "fastembed_local"
    embedding_model: str | None = "BAAI/bge-small-en-v1.5"
    embedding_vector_dimension: int | None = Field(default=384, gt=0)
    embedding_cache_location: str | None = "./models/fastembed"
    embedding_api_key: SecretStr | None = None

    # Edge-to-central synchronization foundation. Values here are references
    # and transport settings only; no secret material is embedded in config.
    global_backend_base_url: str | None = None
    edge_credential_reference: str | None = None
    edge_token_reference: str | None = None
    edge_certificate_reference: str | None = None
    sync_transport_timeout_seconds: float = Field(default=10.0, gt=0.0, le=300.0)
    sync_retry_initial_seconds: float = Field(default=5.0, gt=0.0, le=3600.0)
    sync_retry_max_seconds: float = Field(default=300.0, gt=0.0, le=86400.0)
    sync_retry_max_attempts: int = Field(default=10, ge=1, le=10000)

    semantic_top_k: int = Field(default=5, gt=0, le=100)
    # Qdrant score ranges depend on the configured distance/model. This is a
    # ranking threshold only, never a confidence/probability threshold.
    semantic_score_threshold: float | None = None

    # Optional advisory AI configuration. It is intentionally independent of Qdrant.
    ai_enabled: bool = False
    ai_provider: str | None = "groq"
    ai_model: str | None = "qwen/qwen3.8-27b"
    groq_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)

    @field_validator(
        "qdrant_url",
        "qdrant_location",
        "local_node_id",
        "embedding_provider",
        "embedding_model",
        "embedding_cache_location",
        "global_backend_base_url",
        "edge_credential_reference",
        "edge_token_reference",
        "edge_certificate_reference",
        "ai_provider",
        "ai_model",
        mode="before",
    )
    @classmethod
    def blank_optional_text_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("qdrant_api_key", "embedding_api_key", "groq_api_key", mode="before")
    @classmethod
    def blank_optional_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("qdrant_collection")
    @classmethod
    def qdrant_collection_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("qdrant_collection must not be blank")
        return value

    @model_validator(mode="after")
    def validate_local_node_configuration(self) -> "Settings":
        if self.demo_mode:
            from app.demo.fixtures import (
                DEMO_EMBEDDING_DIMENSION, DEMO_EMBEDDING_MODEL, DEMO_EMBEDDING_PROVIDER,
                DEMO_MACHINE_ID, DEMO_QDRANT_LOCATION, DEMO_GLOBAL_BACKEND_BASE_URL,
                DEMO_RETURN_TO_SERVICE_POLICY_IDENTIFIER, DEMO_RETURN_TO_SERVICE_POLICY_REVISION,
            )
            if self.local_machine_id is None:
                self.local_machine_id = DEMO_MACHINE_ID
            self.semantic_search_enabled = True
            if self.qdrant_url is None and self.qdrant_location is None:
                self.qdrant_location = DEMO_QDRANT_LOCATION
            if self.global_backend_base_url is None:
                self.global_backend_base_url = DEMO_GLOBAL_BACKEND_BASE_URL
            if self.embedding_provider in (None, "fastembed_local"):
                self.embedding_provider = DEMO_EMBEDDING_PROVIDER
                self.embedding_model = DEMO_EMBEDDING_MODEL
                self.embedding_vector_dimension = DEMO_EMBEDDING_DIMENSION
                self.embedding_cache_location = None
            self.return_to_service_policy_identifier = DEMO_RETURN_TO_SERVICE_POLICY_IDENTIFIER
            self.return_to_service_policy_revision = DEMO_RETURN_TO_SERVICE_POLICY_REVISION
            if not self.return_to_service_do_not_return_incident_statuses:
                self.return_to_service_do_not_return_incident_statuses = (IncidentStatus.OPEN, IncidentStatus.RECURRED)
        # Optional integrations may be absent without invalidating canonical
        # SQLite operation. When supplied, malformed transport locations are
        # rejected eagerly so failure is explicit rather than deferred.
        ensure_supported_major(self.transport_schema_version)
        if self.qdrant_url is not None:
            TypeAdapter(AnyHttpUrl).validate_python(self.qdrant_url)
        if self.global_backend_base_url is not None:
            TypeAdapter(AnyHttpUrl).validate_python(self.global_backend_base_url)
        if self.qdrant_url is not None and self.qdrant_location is not None:
            raise ValueError("configure either qdrant_url or qdrant_location, not both")
        if self.sync_retry_max_seconds < self.sync_retry_initial_seconds:
            raise ValueError("sync_retry_max_seconds must be >= sync_retry_initial_seconds")
        if (self.embedding_provider or "").strip().lower() == "fastembed_local":
            if self.embedding_model != "BAAI/bge-small-en-v1.5":
                raise ValueError(
                    "fastembed_local supports only pinned model BAAI/bge-small-en-v1.5"
                )
            if self.embedding_vector_dimension != 384:
                raise ValueError(
                    "BAAI/bge-small-en-v1.5 requires embedding_vector_dimension=384"
                )
            if not self.embedding_cache_location:
                raise ValueError("fastembed_local requires embedding_cache_location")
        overlap = set(self.return_to_service_do_not_return_incident_statuses) & set(
            self.return_to_service_verification_required_incident_statuses
        )
        if overlap:
            names = ",".join(sorted(item.value for item in overlap))
            raise ValueError(
                "return-to-service incident status cannot map to two states: " + names
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
