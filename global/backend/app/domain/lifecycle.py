"""Legacy edge lifecycle vocabulary retained for compatibility only.

No global API or service imports this module to execute lifecycle, verification,
recurrence, or return-to-service decisions. Authoritative transitions arrive via
synchronization and are persisted as supplied by the edge.
"""

from collections.abc import Mapping
from types import MappingProxyType

from app.domain.enums import IncidentStatus


class InvalidIncidentTransition(ValueError):
    """Raised when a requested incident lifecycle transition is not allowed."""


_ALLOWED_INCIDENT_TRANSITIONS: Mapping[IncidentStatus, frozenset[IncidentStatus]] = (
    MappingProxyType(
        {
            IncidentStatus.OPEN: frozenset({IncidentStatus.VERIFYING}),
            IncidentStatus.VERIFYING: frozenset(
                {IncidentStatus.VERIFIED, IncidentStatus.RECURRED}
            ),
            IncidentStatus.VERIFIED: frozenset({IncidentStatus.RECURRED}),
            IncidentStatus.RECURRED: frozenset({IncidentStatus.VERIFYING}),
        }
    )
)


def allowed_incident_transitions(
    current: IncidentStatus,
) -> frozenset[IncidentStatus]:
    return _ALLOWED_INCIDENT_TRANSITIONS[current]


def validate_incident_transition(
    current: IncidentStatus,
    target: IncidentStatus,
) -> None:
    if target not in _ALLOWED_INCIDENT_TRANSITIONS[current]:
        raise InvalidIncidentTransition(
            f"Incident transition {current.value} -> {target.value} is not allowed"
        )
