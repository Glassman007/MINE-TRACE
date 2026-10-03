from __future__ import annotations

from typing import Protocol

from app.schemas.sync import SyncAcknowledgement, SyncEnvelope


class SyncTransportError(RuntimeError):
    def __init__(self, message: str, *, transport_available: bool | None) -> None:
        self.transport_available = transport_available
        super().__init__(message)


class SyncTransportNotConfiguredError(SyncTransportError):
    def __init__(self, message: str = "global synchronization transport is not configured") -> None:
        super().__init__(message, transport_available=None)


class SyncTransportUnavailableError(SyncTransportError):
    def __init__(self, message: str) -> None:
        super().__init__(message, transport_available=False)


class SyncMalformedAcknowledgementError(SyncTransportError):
    def __init__(self, message: str) -> None:
        super().__init__(message, transport_available=True)


class SyncUnsupportedSchemaResponseError(SyncTransportError):
    def __init__(self, message: str) -> None:
        super().__init__(message, transport_available=True)


class SyncTransport(Protocol):
    def send(self, envelope: SyncEnvelope) -> SyncAcknowledgement: ...
