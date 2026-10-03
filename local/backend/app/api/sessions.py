from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.session_reports import MachineSessionReportResponse
from app.schemas.sessions import (
    OperatingSessionCloseRequest,
    OperatingSessionOpenRequest,
    OperatingSessionResponse,
    OperatingSessionRolloverRequest,
    OperatingSessionRolloverResponse,
)
from app.services.session_reports import SessionReportNotFoundError
from app.services.sessions import (
    ActiveOperatingSessionExistsError,
    ConfiguredMachineNotFoundError,
    LocalMachineNotConfiguredError,
    NoActiveOperatingSessionError,
    OperatingSessionError,
    OperatingSessionNotFoundError,
    OperatingSessionService,
    OperatingSessionStateError,
    OperatingSessionTimeError,
)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _service(session: Session, settings: Settings) -> OperatingSessionService:
    return OperatingSessionService(uow_factory_for_session(session), settings)


def _raise_session_error(exc: OperatingSessionError):
    if isinstance(exc, LocalMachineNotConfiguredError):
        return api_error(status_code=503, code="LOCAL_MACHINE_NOT_CONFIGURED", message=str(exc))
    if isinstance(exc, ConfiguredMachineNotFoundError):
        return api_error(status_code=404, code="CONFIGURED_MACHINE_NOT_FOUND", message=str(exc))
    if isinstance(exc, (OperatingSessionNotFoundError, NoActiveOperatingSessionError)):
        return api_error(status_code=404, code="OPERATING_SESSION_NOT_FOUND", message=str(exc))
    if isinstance(
        exc,
        (ActiveOperatingSessionExistsError, OperatingSessionStateError, OperatingSessionTimeError),
    ):
        return api_error(status_code=409, code="OPERATING_SESSION_CONFLICT", message=str(exc))
    return api_error(status_code=400, code="OPERATING_SESSION_ERROR", message=str(exc))


@router.post("", response_model=OperatingSessionResponse, status_code=201)
def open_session(
    request: OperatingSessionOpenRequest,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> OperatingSessionResponse:
    try:
        return _service(session, settings).open_session(started_at=request.started_at)
    except OperatingSessionError as exc:
        raise _raise_session_error(exc) from exc


@router.get("/active", response_model=OperatingSessionResponse)
def get_active_session(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> OperatingSessionResponse:
    try:
        return _service(session, settings).get_active_session()
    except OperatingSessionError as exc:
        raise _raise_session_error(exc) from exc


@router.post("/rollover", response_model=OperatingSessionRolloverResponse)
def rollover_session(
    request: OperatingSessionRolloverRequest,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> OperatingSessionRolloverResponse:
    try:
        result = _service(session, settings).rollover(
            ended_at=request.ended_at,
            new_started_at=request.new_started_at,
            operating_hours=request.operating_hours,
        )
        return OperatingSessionRolloverResponse(
            closed_session=result.closed_session,
            new_session=result.new_session,
        )
    except OperatingSessionError as exc:
        raise _raise_session_error(exc) from exc


@router.get("/{session_id}", response_model=OperatingSessionResponse)
def get_session(
    session_id: UUID,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> OperatingSessionResponse:
    try:
        return _service(session, settings).get_session(session_id)
    except OperatingSessionError as exc:
        raise _raise_session_error(exc) from exc


@router.post("/{session_id}/close", response_model=OperatingSessionResponse)
def close_session(
    session_id: UUID,
    request: OperatingSessionCloseRequest,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> OperatingSessionResponse:
    try:
        return _service(session, settings).close_session(
            session_id,
            ended_at=request.ended_at,
            operating_hours=request.operating_hours,
        ).session
    except OperatingSessionError as exc:
        raise _raise_session_error(exc) from exc


@router.get(
    "/{session_id}/report",
    response_model=MachineSessionReportResponse,
    response_model_exclude_none=True,
)
def get_session_report(
    session_id: UUID,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> MachineSessionReportResponse:
    try:
        return _service(session, settings).get_report(session_id)
    except SessionReportNotFoundError as exc:
        raise api_error(status_code=404, code="SESSION_REPORT_NOT_FOUND", message=str(exc)) from exc
    except OperatingSessionError as exc:
        raise _raise_session_error(exc) from exc
