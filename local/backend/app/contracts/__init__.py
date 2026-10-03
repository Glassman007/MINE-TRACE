"""Versioned edge-to-central transport contract helpers."""

from app.contracts.versioning import (
    CURRENT_TRANSPORT_SCHEMA_VERSION,
    SUPPORTED_TRANSPORT_MAJOR,
    SchemaVersion,
    UnsupportedSchemaMajorError,
    ensure_supported_major,
    parse_schema_version,
)

__all__ = [
    "CURRENT_TRANSPORT_SCHEMA_VERSION",
    "SUPPORTED_TRANSPORT_MAJOR",
    "SchemaVersion",
    "UnsupportedSchemaMajorError",
    "ensure_supported_major",
    "parse_schema_version",
]
