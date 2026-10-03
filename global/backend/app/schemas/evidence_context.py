"""Strongly typed historical evidence context and attachment metadata schemas."""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from app.domain.enums import ContextQuality

NonEmptyString = Annotated[str, Field(min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class ContextDimensionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: JsonValue | None
    quality: ContextQuality
    freshness_basis: NonEmptyString


class ContextSnapshotInput(BaseModel):
    """Fixed evidence-time context dimensions.

    ``freshness_basis`` is intentionally an opaque, non-empty source-provided
    string because the specification requires the basis to be preserved but does
    not define a controlled vocabulary or timestamp-only representation.
    """

    model_config = ConfigDict(extra="forbid")

    shift: ContextDimensionInput
    location: ContextDimensionInput
    machine_operating_state: ContextDimensionInput
    workload: ContextDimensionInput
    environment: ContextDimensionInput


class EvidenceAttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_type: NonEmptyString
    storage_reference: NonEmptyString
    mime_type: NonEmptyString
    file_size: NonNegativeInt
    checksum: NonEmptyString
    created_at: AwareDatetime
