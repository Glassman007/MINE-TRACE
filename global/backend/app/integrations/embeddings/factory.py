"""Embedding-provider selection from typed application configuration."""

from __future__ import annotations

from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import Settings
from app.integrations.embeddings.base import (
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
)
from app.integrations.embeddings.fastembed_local import (
    FASTEMBED_PROVIDER,
    FastEmbedEmbeddingProvider,
    FastEmbedModel,
)
from app.integrations.embeddings.qdrant_cloud import (
    QDRANT_CLOUD_INFERENCE_PROVIDER,
    QdrantCloudInferenceClient,
    QdrantCloudInferenceEmbeddingProvider,
)


def build_embedding_provider(
    settings: Settings,
    *,
    qdrant_cloud_client: QdrantCloudInferenceClient | None = None,
    fastembed_model: FastEmbedModel | None = None,
    observability: MLAIObservability | None = None,
) -> EmbeddingProvider:
    """Build the configured adapter.

    FastEmbed initialization is local and may populate its model cache on first
    use. Remote providers retain their existing injected-transport boundary.
    """

    provider = (settings.embedding_provider or "").strip().lower()
    if not provider:
        raise EmbeddingProviderUnavailableError("embedding provider is not configured")
    if not settings.embedding_model:
        raise EmbeddingProviderUnavailableError("embedding model is not configured")

    if provider == FASTEMBED_PROVIDER:
        if settings.embedding_dimension is None:
            raise EmbeddingProviderUnavailableError(
                "embedding dimension is required for FastEmbed"
            )
        return FastEmbedEmbeddingProvider(
            model=settings.embedding_model,
            expected_dimension=settings.embedding_dimension,
            model_instance=fastembed_model,
            observability=observability,
        )

    if provider == QDRANT_CLOUD_INFERENCE_PROVIDER:
        return QdrantCloudInferenceEmbeddingProvider(
            model=settings.embedding_model,
            timeout_seconds=settings.qdrant_timeout_seconds,
            client=qdrant_cloud_client,
            observability=observability,
        )

    raise EmbeddingProviderUnavailableError(
        f"unsupported embedding provider: {settings.embedding_provider}"
    )
