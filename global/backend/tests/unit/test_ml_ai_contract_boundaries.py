"""Contract-level tests for the MINE-TRACE ML/AI authority boundary."""

from __future__ import annotations

import inspect
from dataclasses import fields

from app.integrations.embeddings import (
    EmbeddingProvider,
    FastEmbedEmbeddingProvider,
    QdrantCloudInferenceClient,
    QdrantCloudInferenceEmbeddingProvider,
)
from app.integrations.llm import AIProvider, LLMProvider
from app.integrations.qdrant import QdrantSemanticIndex
from app.integrations.semantic import SemanticIndex, SemanticIndexHit
from app.services.ml_ai_contracts import (
    AIOutputValidator,
    DeterministicFallback,
    EvidenceBundleBuilder,
    SemanticSearchService,
)


FORBIDDEN_AUTHORITY_TERMS = {
    "close",
    "transition",
    "verify",
    "repair",
    "alter",
    "update",
    "delete",
    "owner",
    "severity",
    "acknowledge",
    "handover",
    "recurrence",
    "recur",
    "certify",
    "certification",
    "maintenance",
}


def _public_methods(contract: type[object]) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(contract)
        if not name.startswith("_") and inspect.isfunction(member)
    }


def test_ml_ai_contracts_expose_only_narrow_derived_operations() -> None:
    expected = {
        EmbeddingProvider: {"embed_document", "embed_documents", "embed_query"},
        QdrantCloudInferenceClient: {"embed_documents", "embed_queries"},
        QdrantCloudInferenceEmbeddingProvider: {"embed_document", "embed_documents", "embed_query", "probe_availability"},
        FastEmbedEmbeddingProvider: {"embed_document", "embed_documents", "embed_query", "probe_availability"},
        SemanticIndex: {"search", "upsert_evidence"},
        QdrantSemanticIndex: {"search", "upsert_evidence"},
        SemanticSearchService: {"search_similar_history"},
        EvidenceBundleBuilder: {"build"},
        AIProvider: {"analyze"},
        LLMProvider: {"generate_analysis"},
        AIOutputValidator: {"validate"},
        DeterministicFallback: {"build"},
    }

    for contract, allowed_methods in expected.items():
        assert _public_methods(contract) == allowed_methods


def test_ml_ai_contracts_do_not_expose_canonical_authority_methods() -> None:
    contracts = (
        EmbeddingProvider,
    FastEmbedEmbeddingProvider,
        QdrantCloudInferenceClient,
        QdrantCloudInferenceEmbeddingProvider,
        FastEmbedEmbeddingProvider,
        SemanticIndex,
        QdrantSemanticIndex,
        SemanticSearchService,
        EvidenceBundleBuilder,
        AIProvider,
        LLMProvider,
        AIOutputValidator,
        DeterministicFallback,
    )

    for contract in contracts:
        for method_name in _public_methods(contract):
            tokens = set(method_name.lower().split("_"))
            assert tokens.isdisjoint(FORBIDDEN_AUTHORITY_TERMS), (
                f"{contract.__name__}.{method_name} crosses the ML/AI authority boundary"
            )


def test_semantic_index_hit_contains_only_derived_reference_and_score() -> None:
    assert [field.name for field in fields(SemanticIndexHit)] == ["evidence_id", "score"]


def test_ai_provider_receives_only_the_sealed_evidence_bundle() -> None:
    signature = inspect.signature(AIProvider.analyze)
    assert list(signature.parameters) == ["self", "evidence_bundle"]


def test_validator_receives_output_and_bundle_but_no_repository_or_session() -> None:
    signature = inspect.signature(AIOutputValidator.validate)
    assert list(signature.parameters) == ["self", "candidate", "evidence_bundle"]
