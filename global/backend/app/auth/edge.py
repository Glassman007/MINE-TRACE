from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Mapping, Protocol
from uuid import UUID


class EdgeAuthenticationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EdgePrincipal:
    machine_id: UUID


class EdgeAuthenticator(Protocol):
    def authenticate(self, *, node_id: str | None, authorization: str | None) -> EdgePrincipal: ...


def hash_edge_token(token: str) -> str:
    if not token:
        raise ValueError("edge token must not be empty")
    return f"sha256:{hashlib.sha256(token.encode('utf-8')).hexdigest()}"


class HashedBearerEdgeAuthenticator:
    """Small replaceable edge-auth boundary for development and MVP deployments.

    Configuration maps machine UUID -> SHA-256 token digest. The raw bearer
    secret is never required in source control. Production deployments must use
    TLS because a static bearer token is replayable if intercepted.
    """

    def __init__(self, token_hashes: Mapping[str, str]) -> None:
        normalized: dict[UUID, str] = {}
        for machine_id, digest in token_hashes.items():
            normalized[UUID(str(machine_id))] = str(digest).lower()
        self._token_hashes = normalized

    def authenticate(self, *, node_id: str | None, authorization: str | None) -> EdgePrincipal:
        if not node_id:
            raise EdgeAuthenticationError("X-Mine-Trace-Node-Id is required")
        try:
            machine_id = UUID(node_id)
        except (TypeError, ValueError) as exc:
            raise EdgeAuthenticationError("edge node id must be a UUID") from exc

        expected = self._token_hashes.get(machine_id)
        if expected is None:
            raise EdgeAuthenticationError("edge node is not registered")
        if not authorization or not authorization.startswith("Bearer "):
            raise EdgeAuthenticationError("Bearer edge token is required")
        token = authorization[7:]
        supplied = hash_edge_token(token)
        if not hmac.compare_digest(expected, supplied):
            raise EdgeAuthenticationError("edge token does not match node identity")
        return EdgePrincipal(machine_id=machine_id)
