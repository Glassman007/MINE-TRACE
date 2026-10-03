from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RevisionDisposition(StrEnum):
    EXACT_REDELIVERY = "EXACT_REDELIVERY"
    PACKAGE_ID_REUSE_CONFLICT = "PACKAGE_ID_REUSE_CONFLICT"
    LOGICAL_DUPLICATE = "LOGICAL_DUPLICATE"
    SAME_REVISION_CONFLICT = "SAME_REVISION_CONFLICT"
    OUT_OF_ORDER_CONFLICT = "OUT_OF_ORDER_CONFLICT"
    ACCEPT = "ACCEPT"


@dataclass(frozen=True, slots=True)
class RevisionDecision:
    disposition: RevisionDisposition
    conflict_type: str | None = None


@dataclass(frozen=True, slots=True)
class RevisionState:
    incoming_revision: int
    incoming_checksum: str
    incoming_fingerprint: str
    # If the same package_id has ever been seen, this is the checksum stored for
    # that package identity. None means the package_id is new.
    package_id_existing_checksum: str | None = None
    # If this logical machine/session/revision exists, this is its canonical
    # content fingerprint.
    logical_revision_existing_fingerprint: str | None = None
    latest_accepted_revision: int | None = None


def decide_revision(state: RevisionState) -> RevisionDecision:
    """Apply the locked deterministic sync revision policy without I/O."""

    if state.incoming_revision < 1:
        raise ValueError("incoming_revision must be >= 1")

    if state.package_id_existing_checksum is not None:
        if state.package_id_existing_checksum == state.incoming_checksum:
            return RevisionDecision(RevisionDisposition.EXACT_REDELIVERY)
        return RevisionDecision(
            RevisionDisposition.PACKAGE_ID_REUSE_CONFLICT,
            conflict_type="PACKAGE_ID_REUSE",
        )

    if state.logical_revision_existing_fingerprint is not None:
        if state.logical_revision_existing_fingerprint == state.incoming_fingerprint:
            return RevisionDecision(RevisionDisposition.LOGICAL_DUPLICATE)
        return RevisionDecision(
            RevisionDisposition.SAME_REVISION_CONFLICT,
            conflict_type="SAME_REVISION_CONTENT_MISMATCH",
        )

    if (
        state.latest_accepted_revision is not None
        and state.incoming_revision < state.latest_accepted_revision
    ):
        return RevisionDecision(
            RevisionDisposition.OUT_OF_ORDER_CONFLICT,
            conflict_type="OUT_OF_ORDER_REVISION",
        )

    return RevisionDecision(RevisionDisposition.ACCEPT)
