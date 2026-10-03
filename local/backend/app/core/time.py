"""Canonical timestamp handling for SQLite-backed historical ordering."""

from datetime import datetime, timezone


def normalize_to_utc(value: datetime) -> datetime:
    """Return the same instant normalized to UTC.

    Controlled ingestion uses aware timestamps. Normalizing before SQLite storage
    prevents mixed source offsets from corrupting chronological ordering when the
    SQLite driver drops timezone-offset metadata from DATETIME values.
    """

    if value.tzinfo is None:
        # Persisted SQLite DATETIME values are interpreted as UTC by this backend.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def restore_utc(value: datetime | None) -> datetime | None:
    """Expose persisted SQLite timestamps as explicit UTC instants."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
