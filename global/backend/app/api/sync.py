from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.auth.edge import EdgeAuthenticationError, EdgeAuthenticator, HashedBearerEdgeAuthenticator
from app.contracts.sync import (
    ChecksumMismatchError,
    SyncAcknowledgement,
    SyncAcknowledgementStatus,
    SyncContractError,
    UnsupportedSchemaVersionError,
    parse_sync_envelope,
    prevalidate_schema_version,
    validate_envelope_checksum,
)
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.services.sync_ingestion import GlobalSyncIngestionService, SyncIngestionError
from app.services.fleet_queries import FleetQueryService
from app.schemas.sync_reads import SyncConflictCollectionResponse, SyncHealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["Synchronization"])


def get_edge_authenticator(settings: Settings = Depends(get_settings)) -> EdgeAuthenticator:
    return HashedBearerEdgeAuthenticator(settings.edge_node_token_hashes)


def _run_post_commit_semantic_indexing(app: Any, evidence_ids: tuple) -> None:
    """Best-effort derived work. Canonical commit has already completed."""

    coordinator = getattr(app.state, "semantic_indexing_coordinator", None)
    service = getattr(app.state, "semantic_indexing_service", None)
    if coordinator is None and service is None:
        logger.info(
            "sync_semantic_indexing_not_configured",
            extra={"evidence_count": len(evidence_ids)},
        )
        return
    try:
        if coordinator is not None:
            coordinator.process_evidence_ids(evidence_ids)
        else:
            # Compatibility boundary for injected Prompt-4 test doubles. Runtime
            # global deployments use the durable coordinator above.
            service.batch_index(evidence_ids)
    except Exception as exc:  # optional derived capability boundary
        logger.warning(
            "sync_semantic_indexing_failed_after_commit",
            extra={"error_type": type(exc).__name__, "evidence_count": len(evidence_ids)},
        )


@router.post("/packages", response_model=SyncAcknowledgement)
def ingest_sync_package(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] = Body(...),
    session: Session = Depends(get_db_session),
    authenticator: EdgeAuthenticator = Depends(get_edge_authenticator),
) -> SyncAcknowledgement:
    # 1. Authenticate before inspecting any payload business identity.
    try:
        principal = authenticator.authenticate(
            node_id=request.headers.get("X-Mine-Trace-Node-Id"),
            authorization=request.headers.get("Authorization"),
        )
    except EdgeAuthenticationError as exc:
        raise api_error(status_code=401, code="EDGE_AUTHENTICATION_FAILED", message=str(exc)) from exc

    # 2. Read only schema_version before parsing business fields.
    try:
        prevalidate_schema_version(payload)
    except UnsupportedSchemaVersionError as exc:
        raise api_error(status_code=422, code="UNSUPPORTED_SYNC_SCHEMA_VERSION", message=str(exc)) from exc
    except SyncContractError as exc:
        raise api_error(status_code=422, code="INVALID_SYNC_SCHEMA_VERSION", message=str(exc)) from exc

    # 3. Parse and validate all explicit identities/relationships.
    try:
        envelope = parse_sync_envelope(payload)
    except UnsupportedSchemaVersionError as exc:
        raise api_error(status_code=422, code="UNSUPPORTED_SYNC_SCHEMA_VERSION", message=str(exc)) from exc
    except (SyncContractError, ValidationError) as exc:
        details = exc.errors() if isinstance(exc, ValidationError) else None
        raise api_error(
            status_code=422,
            code="INVALID_SYNC_ENVELOPE",
            message="sync envelope validation failed",
            details=details or str(exc),
        ) from exc

    if principal.machine_id != envelope.source_machine_id:
        raise api_error(
            status_code=403,
            code="EDGE_NODE_MACHINE_MISMATCH",
            message="authenticated edge node does not match source_machine_id",
        )

    # 4. Validate deterministic transport checksum before any database writes.
    try:
        validate_envelope_checksum(envelope)
    except ChecksumMismatchError as exc:
        raise api_error(status_code=422, code="SYNC_CHECKSUM_MISMATCH", message=str(exc)) from exc

    # 5-14. All canonical idempotency/revision/persistence operations execute in
    # one GlobalSyncIngestionService transaction.
    try:
        result = GlobalSyncIngestionService(session).ingest(envelope)
    except SyncIngestionError as exc:
        raise api_error(status_code=exc.status_code, code=exc.code, message=exc.message) from exc

    # 15. The service has already exited/committed its transaction. Derived
    # indexing is dispatched only now and is guarded so Qdrant/embedding failure
    # cannot alter the canonical sync acknowledgement.
    if result.semantic_evidence_ids:
        background_tasks.add_task(
            _run_post_commit_semantic_indexing,
            request.app,
            result.semantic_evidence_ids,
        )

    if result.acknowledgement.status is SyncAcknowledgementStatus.CONFLICT:
        response.status_code = 409
    return result.acknowledgement


def _capability_tuple(app: Any, attribute: str, fallback_status: str) -> tuple[str, str | None]:
    state = getattr(app.state, attribute, None)
    if state is None:
        return fallback_status, "capability_state_not_initialized"
    status = getattr(state, "status", fallback_status)
    return getattr(status, "value", str(status)), getattr(state, "reason", None)


@router.get("/health", response_model=SyncHealthResponse)
def sync_health(
    request: Request,
    stale_after_hours: float | None = Query(default=None, gt=0.0, le=8760.0),
    session: Session = Depends(get_db_session),
) -> SyncHealthResponse:
    semantic_status, semantic_reason = _capability_tuple(
        request.app, "semantic_retrieval_capability", "UNAVAILABLE"
    )
    embedding_status, embedding_reason = _capability_tuple(
        request.app, "embedding_provider_capability", "UNAVAILABLE"
    )
    ai_status, ai_reason = _capability_tuple(
        request.app, "ai_capability", "DISABLED"
    )
    return FleetQueryService(session).sync_health(
        semantic_status=semantic_status,
        semantic_reason=semantic_reason,
        embedding_status=embedding_status,
        embedding_reason=embedding_reason,
        ai_status=ai_status,
        ai_reason=ai_reason,
        stale_after_hours=stale_after_hours,
    )


@router.get("/conflicts", response_model=SyncConflictCollectionResponse)
def sync_conflicts(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    unresolved_only: bool = Query(default=False),
    session: Session = Depends(get_db_session),
) -> SyncConflictCollectionResponse:
    return FleetQueryService(session).sync_conflicts(
        offset=offset, limit=limit, unresolved_only=unresolved_only
    )
