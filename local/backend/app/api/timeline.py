"""Historical evidence timeline transport API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.db.session import get_db_session
from app.schemas.timeline import MachineTimelineResponse
from app.services.timeline import (
    InvalidTimelineRangeError,
    TimelineService,
    UnknownTimelineComponentError,
    UnknownTimelineMachineError,
)

router = APIRouter(prefix="/machines", tags=["Timeline"])


@router.get("/{machine_id}/timeline", response_model=MachineTimelineResponse)
def get_machine_timeline(
    machine_id: UUID,
    component_id: UUID | None = Query(default=None),
    from_timestamp: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_timestamp: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    session: Session = Depends(get_db_session),
) -> MachineTimelineResponse:
    service = TimelineService(uow_factory_for_session(session))
    try:
        return service.get_machine_timeline(
            machine_id,
            component_id=component_id,
            start=from_timestamp,
            end=to_timestamp,
        )
    except UnknownTimelineMachineError as exc:
        raise api_error(status_code=404, code="MACHINE_NOT_FOUND", message=str(exc)) from exc
    except UnknownTimelineComponentError as exc:
        raise api_error(status_code=404, code="COMPONENT_NOT_FOUND", message=str(exc)) from exc
    except InvalidTimelineRangeError as exc:
        raise api_error(status_code=422, code="INVALID_TIMELINE_RANGE", message=str(exc)) from exc
