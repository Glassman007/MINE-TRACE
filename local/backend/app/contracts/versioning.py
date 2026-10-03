from __future__ import annotations

import re
from dataclasses import dataclass

_SCHEMA_VERSION_RE = re.compile(r"^(?P<major>[1-9]\d*)\.(?P<minor>\d+)$")

CURRENT_TRANSPORT_SCHEMA_VERSION = "1.0"
SUPPORTED_TRANSPORT_MAJOR = 1


class TransportSchemaVersionError(ValueError):
    pass


class UnsupportedSchemaMajorError(TransportSchemaVersionError):
    def __init__(self, version: str, *, supported_major: int = SUPPORTED_TRANSPORT_MAJOR) -> None:
        self.version = version
        self.supported_major = supported_major
        super().__init__(
            f"unsupported transport schema major in {version!r}; supported major is {supported_major}"
        )


@dataclass(frozen=True, slots=True, order=True)
class SchemaVersion:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


def parse_schema_version(value: str) -> SchemaVersion:
    if not isinstance(value, str):
        raise TransportSchemaVersionError("schema_version must be a string")
    match = _SCHEMA_VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise TransportSchemaVersionError(
            "schema_version must use MAJOR.MINOR format with a positive major"
        )
    return SchemaVersion(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
    )


def ensure_supported_major(value: str) -> SchemaVersion:
    parsed = parse_schema_version(value)
    if parsed.major != SUPPORTED_TRANSPORT_MAJOR:
        raise UnsupportedSchemaMajorError(value)
    return parsed
