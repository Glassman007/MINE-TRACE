from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from app.contracts.versioning import UnsupportedSchemaMajorError, ensure_supported_major
from app.core.settings import Settings
from app.core.time import normalize_to_utc
from app.domain.enums import SyncConflictState, SyncOutboxState
from app.integrations.sync import (
    HttpSyncTransport,
    SyncMalformedAcknowledgementError,
    SyncTransport,
    SyncTransportError,
    SyncTransportNotConfiguredError,
    SyncUnsupportedSchemaResponseError,
)
from app.models import SyncConflictRecord, SyncOutboxItemRecord
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.session_reports import MachineSessionReport
from app.schemas.sync import (
    IncidentUpdate,
    SyncAcknowledgement,
    SyncAcknowledgementStatus,
    SyncEnvelope,
)


class SyncServiceError(RuntimeError):
    pass


class SyncOutboxItemNotFoundError(SyncServiceError):
    pass


class SyncPayloadIntegrityError(SyncServiceError):
    pass


class SyncRetryExhaustedError(SyncServiceError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def calculate_envelope_checksum(payload: dict[str, Any]) -> str:
    content = dict(payload)
    content.pop("checksum", None)
    return _sha256_json(content)


def build_sync_envelope(report: MachineSessionReport, settings: Settings) -> SyncEnvelope:
    ensure_supported_major(report.schema_version)
    package_id = uuid5(
        NAMESPACE_URL,
        (
            "mine-trace-sync-package:"
            f"{report.report_id}:{report.sync_metadata.local_revision}:"
            f"{report.sync_metadata.report_revision}"
        ),
    )
    updates = [
        IncidentUpdate(
            schema_version=report.schema_version,
            incident_id=item.incident_id,
            machine_id=report.machine_id,
            component_id=item.component_id,
            state=item.state,
            first_seen=item.first_seen,
            last_seen=item.last_seen,
            occurrence_count=item.occurrence_count,
            severity=item.severity,
            report_revision=report.sync_metadata.report_revision,
        )
        for item in report.incident_summaries
    ]
    base_payload: dict[str, Any] = {
        "schema_version": report.schema_version,
        "package_id": str(package_id),
        "source_machine_id": str(report.machine_id),
        "source_node_id": settings.local_node_id,
        "session_id": str(report.session_id),
        "local_revision": report.sync_metadata.local_revision,
        "report_revision": report.sync_metadata.report_revision,
        "created_at": normalize_to_utc(report.generated_at).isoformat(),
        "machine_session_report": report.model_dump(mode="json", exclude_none=True),
        "incident_updates": [
            item.model_dump(mode="json", exclude_none=True) for item in updates
        ],
        "evidence_manifest": report.evidence_manifest.model_dump(
            mode="json", exclude_none=True
        ),
        # Selection policy for compact text/raw evidence is deliberately not
        # invented here. Empty lists are explicit and raw telemetry stays local.
        "important_text_evidence": [],
        "policy_selected_raw_evidence": [],
    }
    # Normalize UUID/datetime serialization through the contract model before
    # hashing so the durable JSON bytes/structure verify identically on retry.
    provisional = SyncEnvelope.model_validate(
        {**base_payload, "checksum": "sha256:" + "0" * 64}
    ).model_dump(mode="json", exclude_none=True)
    checksum = calculate_envelope_checksum(provisional)
    return SyncEnvelope.model_validate({**provisional, "checksum": checksum})


class SyncOutboxService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        settings: Settings,
        *,
        transport: SyncTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def queue_report_in_uow(
        self, uow: UnitOfWork, report: MachineSessionReport
    ) -> SyncOutboxItemRecord:
        envelope = build_sync_envelope(report, self._settings)
        existing = uow.sync_outbox.get_by_package_revision(
            envelope.package_id, envelope.local_revision
        )
        if existing is not None:
            self._verify_record(existing)
            return existing

        now = normalize_to_utc(self._clock())
        record = SyncOutboxItemRecord(
            id=uuid5(NAMESPACE_URL, f"mine-trace-sync-outbox:{envelope.package_id}"),
            package_id=envelope.package_id,
            machine_id=envelope.source_machine_id,
            session_id=envelope.session_id,
            report_id=envelope.machine_session_report.report_id,
            schema_version=envelope.schema_version,
            local_revision=envelope.local_revision,
            report_revision=envelope.report_revision,
            payload_json=envelope.model_dump(mode="json", exclude_none=True),
            checksum=envelope.checksum,
            state=SyncOutboxState.PENDING,
            attempt_count=0,
            first_attempt_at=None,
            last_attempt_at=None,
            acknowledged_at=None,
            central_revision=None,
            last_error=None,
            transport_available=None,
            transport_checked_at=None,
            created_at=now,
            updated_at=now,
        )
        uow.sync_outbox.add(record)
        uow.flush()
        return record

    def send_item(self, item_id: UUID) -> SyncOutboxItemRecord:
        # Persist SENDING/attempt metadata before the network call so a process
        # interruption leaves a durable retryable record.
        with self._uow_factory() as uow:
            record = self._require_item(uow, item_id)
            if record.state in (SyncOutboxState.ACKNOWLEDGED, SyncOutboxState.CONFLICT):
                uow.commit()
                return record
            if record.attempt_count >= self._settings.sync_retry_max_attempts:
                raise SyncRetryExhaustedError(
                    f"sync retry limit reached for package {record.package_id}"
                )
            try:
                envelope = self._verify_record(record)
            except SyncPayloadIntegrityError as exc:
                now = normalize_to_utc(self._clock())
                record.state = SyncOutboxState.FAILED
                record.last_error = str(exc)
                record.updated_at = now
                uow.commit()
                return record

            now = normalize_to_utc(self._clock())
            record.attempt_count += 1
            if record.first_attempt_at is None:
                record.first_attempt_at = now
            record.last_attempt_at = now
            record.state = SyncOutboxState.SENDING
            record.last_error = None
            record.updated_at = now
            uow.commit()

        transport = self._resolve_transport()
        if transport is None:
            error: SyncTransportError = SyncTransportNotConfiguredError()
            return self._record_transport_failure(item_id, error)

        try:
            raw_ack = transport.send(envelope)
            acknowledgement = self._coerce_acknowledgement(raw_ack)
            if acknowledgement.package_id != envelope.package_id:
                raise SyncMalformedAcknowledgementError(
                    "acknowledgement package_id does not match transmitted package"
                )
        except SyncTransportError as exc:
            return self._record_transport_failure(item_id, exc)
        except Exception as exc:  # fake/custom transports must fail closed too
            error = SyncTransportError(
                f"unexpected sync transport failure: {exc}", transport_available=None
            )
            return self._record_transport_failure(item_id, error)

        now = normalize_to_utc(self._clock())
        with self._uow_factory() as uow:
            record = self._require_item(uow, item_id)
            record.transport_available = True
            record.transport_checked_at = now
            record.updated_at = now
            if acknowledgement.status in (
                SyncAcknowledgementStatus.ACKNOWLEDGED,
                SyncAcknowledgementStatus.DUPLICATE,
            ):
                record.state = SyncOutboxState.ACKNOWLEDGED
                record.acknowledged_at = normalize_to_utc(acknowledgement.acknowledged_at)
                record.central_revision = acknowledgement.central_revision
                record.last_error = None
            elif acknowledgement.status == SyncAcknowledgementStatus.CONFLICT:
                assert acknowledgement.central_revision is not None
                record.state = SyncOutboxState.CONFLICT
                record.central_revision = acknowledgement.central_revision
                record.last_error = acknowledgement.message or "central revision conflict"
                existing = uow.sync_conflicts.get_for_revisions(
                    record.package_id,
                    record.local_revision,
                    acknowledgement.central_revision,
                )
                if existing is None:
                    uow.sync_conflicts.add(
                        SyncConflictRecord(
                            conflict_id=uuid5(
                                NAMESPACE_URL,
                                (
                                    "mine-trace-sync-conflict:"
                                    f"{record.package_id}:{record.local_revision}:"
                                    f"{acknowledgement.central_revision}"
                                ),
                            ),
                            package_id=record.package_id,
                            object_id=record.report_id,
                            machine_id=record.machine_id,
                            session_id=record.session_id,
                            local_revision=record.local_revision,
                            central_revision=acknowledgement.central_revision,
                            detected_at=now,
                            state=SyncConflictState.OPEN,
                            resolution_metadata=acknowledgement.resolution_metadata,
                            resolved_at=None,
                        )
                    )
            else:
                record.state = SyncOutboxState.FAILED
                record.last_error = acknowledgement.message or acknowledgement.status.value
            uow.commit()
            return record

    def _record_transport_failure(
        self, item_id: UUID, error: SyncTransportError
    ) -> SyncOutboxItemRecord:
        now = normalize_to_utc(self._clock())
        with self._uow_factory() as uow:
            record = self._require_item(uow, item_id)
            record.state = SyncOutboxState.FAILED
            record.last_error = str(error)
            record.transport_available = error.transport_available
            record.transport_checked_at = (
                now if error.transport_available is not None else record.transport_checked_at
            )
            record.updated_at = now
            uow.commit()
            return record

    def _resolve_transport(self) -> SyncTransport | None:
        if self._transport is not None:
            return self._transport
        if self._settings.global_backend_base_url is None:
            return None
        return HttpSyncTransport(
            base_url=self._settings.global_backend_base_url,
            timeout_seconds=self._settings.sync_transport_timeout_seconds,
            node_id=self._settings.local_node_id,
        )

    @staticmethod
    def _coerce_acknowledgement(raw: object) -> SyncAcknowledgement:
        if isinstance(raw, SyncAcknowledgement):
            ensure_supported_major(raw.schema_version)
            return raw
        if not isinstance(raw, dict):
            raise SyncMalformedAcknowledgementError(
                "sync transport returned a non-object acknowledgement"
            )
        schema_version = raw.get("schema_version")
        if not isinstance(schema_version, str):
            raise SyncMalformedAcknowledgementError(
                "sync acknowledgement is missing schema_version"
            )
        try:
            ensure_supported_major(schema_version)
        except UnsupportedSchemaMajorError as exc:
            raise SyncUnsupportedSchemaResponseError(str(exc)) from exc
        try:
            return SyncAcknowledgement.model_validate(raw)
        except ValidationError as exc:
            raise SyncMalformedAcknowledgementError(
                f"malformed sync acknowledgement: {exc}"
            ) from exc

    @staticmethod
    def _require_item(uow: UnitOfWork, item_id: UUID) -> SyncOutboxItemRecord:
        record = uow.sync_outbox.get(item_id)
        if record is None:
            raise SyncOutboxItemNotFoundError(f"sync outbox item not found: {item_id}")
        return record

    @staticmethod
    def _verify_record(record: SyncOutboxItemRecord) -> SyncEnvelope:
        try:
            ensure_supported_major(record.schema_version)
            envelope = SyncEnvelope.model_validate(record.payload_json)
        except (ValueError, ValidationError) as exc:
            raise SyncPayloadIntegrityError(
                f"invalid persisted sync envelope for package {record.package_id}: {exc}"
            ) from exc
        calculated = calculate_envelope_checksum(record.payload_json)
        if calculated != record.checksum or envelope.checksum != record.checksum:
            raise SyncPayloadIntegrityError(
                f"sync payload checksum mismatch for package {record.package_id}"
            )
        if (
            envelope.package_id != record.package_id
            or envelope.source_machine_id != record.machine_id
            or envelope.session_id != record.session_id
            or envelope.local_revision != record.local_revision
            or envelope.report_revision != record.report_revision
            or envelope.schema_version != record.schema_version
        ):
            raise SyncPayloadIntegrityError(
                f"persisted sync envelope identity mismatch for package {record.package_id}"
            )
        return envelope


class SyncStatusService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings

    def get_status(self):
        from app.core.time import restore_utc
        from app.schemas.sync import (
            SyncConflictSummary,
            SyncLatestPackageStatus,
            SyncStatusResponse,
        )

        machine_id = self._settings.local_machine_id
        if machine_id is None:
            raise SyncServiceError("local_machine_id is not configured")
        with self._uow_factory() as uow:
            items = list(uow.sync_outbox.list_for_machine(machine_id))
            state_counts = uow.sync_outbox.count_for_machine_by_state(machine_id)
            conflicts = list(uow.sync_conflicts.list_for_machine(machine_id))

            latest = max(
                items,
                key=lambda item: (item.created_at, str(item.id)),
                default=None,
            )
            attempted = [item for item in items if item.last_attempt_at is not None]
            most_recent_attempt = max(
                attempted,
                key=lambda item: (item.last_attempt_at, str(item.id)),
                default=None,
            )
            acknowledged = [item for item in items if item.acknowledged_at is not None]
            most_recent_ack = max(
                acknowledged,
                key=lambda item: (item.acknowledged_at, str(item.id)),
                default=None,
            )
            measured = [
                item
                for item in items
                if item.transport_checked_at is not None
                and item.transport_available is not None
            ]
            most_recent_measurement = max(
                measured,
                key=lambda item: (item.transport_checked_at, str(item.id)),
                default=None,
            )

            return SyncStatusResponse(
                machine_id=machine_id,
                pending_item_count=state_counts.get(SyncOutboxState.PENDING, 0),
                failed_item_count=state_counts.get(SyncOutboxState.FAILED, 0),
                conflict_count=len(conflicts),
                latest_package=(
                    SyncLatestPackageStatus(
                        package_id=latest.package_id,
                        session_id=latest.session_id,
                        state=latest.state.value,
                        local_revision=latest.local_revision,
                        report_revision=latest.report_revision,
                        attempt_count=latest.attempt_count,
                    )
                    if latest is not None
                    else None
                ),
                last_transmission_attempt=(
                    restore_utc(most_recent_attempt.last_attempt_at)
                    if most_recent_attempt is not None
                    else None
                ),
                last_acknowledgement=(
                    restore_utc(most_recent_ack.acknowledged_at)
                    if most_recent_ack is not None
                    else None
                ),
                last_error=(
                    most_recent_attempt.last_error
                    if most_recent_attempt is not None
                    else None
                ),
                transport_configured=self._settings.global_backend_base_url is not None,
                transport_available=(
                    most_recent_measurement.transport_available
                    if most_recent_measurement is not None
                    else None
                ),
                transport_checked_at=(
                    restore_utc(most_recent_measurement.transport_checked_at)
                    if most_recent_measurement is not None
                    else None
                ),
                conflicts=[
                    SyncConflictSummary(
                        conflict_id=item.conflict_id,
                        package_id=item.package_id,
                        object_id=item.object_id,
                        local_revision=item.local_revision,
                        central_revision=item.central_revision,
                        detected_at=restore_utc(item.detected_at),
                        state=item.state.value,
                        resolution_metadata=item.resolution_metadata,
                    )
                    for item in conflicts
                ],
            )
