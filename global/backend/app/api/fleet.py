from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.schemas.fleet import FleetOverviewResponse
from app.services.fleet_queries import FleetQueryService

router = APIRouter(prefix="/fleet", tags=["Fleet"])


@router.get("/overview", response_model=FleetOverviewResponse)
def fleet_overview(
    recent_session_limit: int = Query(default=10, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> FleetOverviewResponse:
    return FleetQueryService(session).overview(recent_session_limit=recent_session_limit)
