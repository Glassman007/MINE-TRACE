"""Canonical timezone-aware timestamp handling for central fleet persistence."""

from datetime import datetime, timezone


def normalize_to_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC instant for PostgreSQL TIMESTAMPTZ fields."""

    if value.tzinfo is None:
        # Legacy synchronized records lacking an explicit offset are interpreted
        # as UTC at this boundary; new transport contracts should send aware times.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def restore_utc(value: datetime | None) -> datetime | None:
    """Normalize a PostgreSQL-returned timestamp to explicit UTC for API output."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
