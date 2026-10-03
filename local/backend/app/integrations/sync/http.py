from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from app.contracts.versioning import UnsupportedSchemaMajorError, ensure_supported_major
from app.integrations.sync.base import (
    SyncMalformedAcknowledgementError,
    SyncTransportUnavailableError,
    SyncUnsupportedSchemaResponseError,
)
from app.schemas.sync import SyncAcknowledgement, SyncEnvelope


class HttpSyncTransport:
    """Small synchronous edge transport; canonical state remains in SQLite."""

    ENVELOPE_PATH = "/api/v1/sync/envelopes"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 10.0,
        node_id: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + self.ENVELOPE_PATH
        self._timeout_seconds = timeout_seconds
        self._node_id = node_id
        self._client = client

    def send(self, envelope: SyncEnvelope) -> SyncAcknowledgement:
        headers = {"Content-Type": "application/json"}
        if self._node_id:
            headers["X-Mine-Trace-Node-ID"] = self._node_id
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self._timeout_seconds)
        try:
            try:
                response = client.post(
                    self._url,
                    json=envelope.model_dump(mode="json", exclude_none=True),
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                raise SyncTransportUnavailableError(f"sync transport unavailable: {exc}") from exc

            try:
                payload: Any = response.json()
            except ValueError as exc:
                raise SyncMalformedAcknowledgementError(
                    f"global backend returned non-JSON acknowledgement (HTTP {response.status_code})"
                ) from exc
            if not isinstance(payload, dict):
                raise SyncMalformedAcknowledgementError(
                    "global backend acknowledgement must be a JSON object"
                )

            # Inspect only the version discriminator first. Unknown majors are
            # rejected before the rest of the acknowledgement is interpreted.
            schema_version = payload.get("schema_version")
            if not isinstance(schema_version, str):
                raise SyncMalformedAcknowledgementError(
                    "global backend acknowledgement is missing schema_version"
                )
            try:
                ensure_supported_major(schema_version)
            except UnsupportedSchemaMajorError as exc:
                raise SyncUnsupportedSchemaResponseError(str(exc)) from exc

            try:
                return SyncAcknowledgement.model_validate(payload)
            except ValidationError as exc:
                raise SyncMalformedAcknowledgementError(
                    f"malformed global acknowledgement: {exc}"
                ) from exc
        finally:
            if owns_client:
                client.close()
