"""HTTP surface for the three controlled MVP ingestion paths."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.ingestion import (
    EvidenceIngestionResponse,
    HumanObservationInput,
    MachineEventInput,
    MaintenanceRecordInput,
)
from app.services.ingestion import (
    ConfiguredMachineMismatchError,
    EvidenceSessionStateError,
    IngestionService,
    UnknownComponentError,
    UnknownMachineError,
    UnknownOperatingSessionError,
)

router = APIRouter(prefix="/evidence", tags=["Evidence"])


def _service(session: Session, settings: Settings) -> IngestionService:
    return IngestionService(uow_factory_for_session(session), settings=settings)


def _identity_error(exc: Exception):
    code = "MACHINE_NOT_FOUND" if isinstance(exc, UnknownMachineError) else "COMPONENT_NOT_FOUND"
    return api_error(status_code=404, code=code, message=str(exc))


@router.post("/machine-events", response_model=EvidenceIngestionResponse)
def ingest_machine_event(
    request: MachineEventInput,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> EvidenceIngestionResponse:
    try:
        result = _service(session, settings).ingest_machine_event_result(request)
    except (UnknownMachineError, UnknownComponentError) as exc:
        raise _identity_error(exc) from exc
    except UnknownOperatingSessionError as exc:
        raise api_error(status_code=404, code="OPERATING_SESSION_NOT_FOUND", message=str(exc)) from exc
    except (EvidenceSessionStateError, ConfiguredMachineMismatchError) as exc:
        raise api_error(status_code=409, code="LOCAL_NODE_CONFLICT", message=str(exc)) from exc
    return EvidenceIngestionResponse(evidence_id=result.evidence_id, session_id=result.session_id, idempotent_replay=result.idempotent_replay)


@router.post("/maintenance-records", response_model=EvidenceIngestionResponse)
def ingest_maintenance_record(
    request: MaintenanceRecordInput,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> EvidenceIngestionResponse:
    try:
        result = _service(session, settings).ingest_maintenance_record_result(request)
    except (UnknownMachineError, UnknownComponentError) as exc:
        raise _identity_error(exc) from exc
    except UnknownOperatingSessionError as exc:
        raise api_error(status_code=404, code="OPERATING_SESSION_NOT_FOUND", message=str(exc)) from exc
    except (EvidenceSessionStateError, ConfiguredMachineMismatchError) as exc:
        raise api_error(status_code=409, code="LOCAL_NODE_CONFLICT", message=str(exc)) from exc
    return EvidenceIngestionResponse(evidence_id=result.evidence_id, session_id=result.session_id, idempotent_replay=result.idempotent_replay)


@router.post("/human-observations", response_model=EvidenceIngestionResponse)
def ingest_human_observation(
    request: HumanObservationInput,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> EvidenceIngestionResponse:
    try:
        result = _service(session, settings).ingest_human_observation_result(request)
    except (UnknownMachineError, UnknownComponentError) as exc:
        raise _identity_error(exc) from exc
    except UnknownOperatingSessionError as exc:
        raise api_error(status_code=404, code="OPERATING_SESSION_NOT_FOUND", message=str(exc)) from exc
    except (EvidenceSessionStateError, ConfiguredMachineMismatchError) as exc:
        raise api_error(status_code=409, code="LOCAL_NODE_CONFLICT", message=str(exc)) from exc
    return EvidenceIngestionResponse(evidence_id=result.evidence_id, session_id=result.session_id, idempotent_replay=result.idempotent_replay)
