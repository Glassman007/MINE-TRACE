"""Shift handover transport APIs."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.db.session import get_db_session
from app.schemas.handover import HandoverPacketResponse
from app.services.handover import (
    CorruptHandoverSnapshotError,
    HandoverAlreadyAcknowledgedError,
    HandoverService,
    UnknownHandoverError,
)

router = APIRouter(prefix="/handovers", tags=["Handover"])


def _service(session: Session) -> HandoverService:
    return HandoverService(uow_factory_for_session(session))


@router.post("", response_model=HandoverPacketResponse, status_code=201)
def create_handover(session: Session = Depends(get_db_session)) -> HandoverPacketResponse:
    return _service(session).create_handover()


@router.get("/{packet_id}", response_model=HandoverPacketResponse)
def get_handover(packet_id: UUID, session: Session = Depends(get_db_session)) -> HandoverPacketResponse:
    try:
        return _service(session).get_handover(packet_id)
    except UnknownHandoverError as exc:
        raise api_error(status_code=404, code="HANDOVER_NOT_FOUND", message=str(exc)) from exc
    except CorruptHandoverSnapshotError as exc:
        raise api_error(status_code=500, code="HANDOVER_SNAPSHOT_CORRUPT", message=str(exc)) from exc


@router.post("/{packet_id}/acknowledge", response_model=HandoverPacketResponse)
def acknowledge_handover(packet_id: UUID, session: Session = Depends(get_db_session)) -> HandoverPacketResponse:
    try:
        return _service(session).acknowledge(packet_id)
    except UnknownHandoverError as exc:
        raise api_error(status_code=404, code="HANDOVER_NOT_FOUND", message=str(exc)) from exc
    except HandoverAlreadyAcknowledgedError as exc:
        raise api_error(status_code=409, code="HANDOVER_ALREADY_ACKNOWLEDGED", message=str(exc)) from exc
