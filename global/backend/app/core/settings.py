from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, SecretStr, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """Typed configuration for the central MINE-TRACE fleet service.

    PostgreSQL is the canonical synchronized fleet store. Qdrant, embeddings and
    advisory AI remain optional derived capabilities and may be unavailable
    without invalidating canonical fleet persistence.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MINE_TRACE_",
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
    )

    app_name: str = "MINE-TRACE Global Backend"
    environment: Literal["development", "test", "staging", "production"] = "development"
    api_prefix: str = ""
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Canonical central persistence. A local PostgreSQL URL is supplied as the
    # development default; deployments should inject their own URL.
    database_url: str = "postgresql+psycopg://mine_trace:mine_trace@localhost:5432/mine_trace"
    db_pool_size: int = Field(default=10, ge=1, le=200)
    db_max_overflow: int = Field(default=20, ge=0, le=500)
    db_pool_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    db_pool_recycle_seconds: int = Field(default=1800, ge=0)

    # Replaceable edge-node authentication boundary. Keys are machine UUIDs and
    # values are sha256:<hex> digests of bearer tokens. Raw tokens are supplied
    # only by edge nodes at runtime and are never stored in source control.
    edge_node_token_hashes: dict[str, str] = Field(default_factory=dict)

    # Retained read-model limits used by reusable global evidence/AI foundations.
    history_lookback_days: int = Field(default=30, gt=0)
    evidence_bundle_limit: int = Field(default=100, gt=0)

    # Optional derived semantic-memory configuration. Qdrant is never canonical.
    semantic_search_enabled: bool = False
    qdrant_url: str | None = None
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = Field(default="mine_trace_evidence", min_length=1)
    qdrant_timeout_seconds: float = Field(default=3.0, gt=0.0, le=120.0)
    qdrant_distance: Literal["cosine", "dot", "euclid", "manhattan"] = "cosine"

    embedding_provider: str | None = "fastembed"
    embedding_model: str | None = "BAAI/bge-small-en-v1.5"
    embedding_api_key: SecretStr | None = None
    embedding_dimension: int | None = Field(default=384, gt=0)

    semantic_top_k: int = Field(default=5, gt=0, le=100)
    semantic_score_threshold: float | None = None

    # Optional advisory AI configuration. It is independent of canonical storage.
    ai_enabled: bool = False
    ai_provider: str | None = "groq"
    ai_model: str | None = None
    groq_api_key: SecretStr | None = None
    ai_api_key: SecretStr | None = None  # legacy optional-provider compatibility
    ai_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)

    @field_validator("edge_node_token_hashes")
    @classmethod
    def validate_edge_node_token_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for machine_id, digest in value.items():
            try:
                canonical_machine_id = str(UUID(str(machine_id)))
            except (TypeError, ValueError) as exc:
                raise ValueError("edge_node_token_hashes keys must be machine UUIDs") from exc
            normalized_digest = str(digest).strip().lower()
            if len(normalized_digest) != 71 or not normalized_digest.startswith("sha256:"):
                raise ValueError("edge node token digests must use sha256:<64 lowercase hex>")
            try:
                int(normalized_digest[7:], 16)
            except ValueError as exc:
                raise ValueError("edge node token digest must contain hexadecimal characters") from exc
            normalized[canonical_machine_id] = normalized_digest
        return normalized

    @field_validator("database_url")
    @classmethod
    def canonical_database_must_be_postgresql(cls, value: str) -> str:
        url = make_url(value.strip())
        if url.get_backend_name() != "postgresql":
            raise ValueError("global canonical database_url must use PostgreSQL")
        return value.strip()

    @field_validator(
        "qdrant_url",
        "embedding_provider",
        "embedding_model",
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

    @field_validator("qdrant_api_key", "embedding_api_key", "groq_api_key", "ai_api_key", mode="before")
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
    def validate_enabled_optional_integrations(self) -> "Settings":
        if self.semantic_search_enabled and self.qdrant_url is not None:
            TypeAdapter(AnyHttpUrl).validate_python(self.qdrant_url)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
