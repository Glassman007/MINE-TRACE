from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.schemas.maintenance import MaintenanceQueueResponse
from app.services.fleet_queries import FleetQueryService

router = APIRouter(tags=["Maintenance"])


@router.get("/maintenance-queue", response_model=MaintenanceQueueResponse)
def maintenance_queue(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> MaintenanceQueueResponse:
    return FleetQueryService(session).maintenance_queue(offset=offset, limit=limit)
