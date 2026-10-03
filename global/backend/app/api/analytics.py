from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.schemas.analytics import AnalyticsBucketsResponse, AnalyticsSummaryResponse, AnalyticsTrendResponse
from app.services.fleet_queries import FleetQueryService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def analytics_summary(session: Session = Depends(get_db_session)) -> AnalyticsSummaryResponse:
    return FleetQueryService(session).analytics_summary()


@router.get("/incidents/by-status", response_model=AnalyticsBucketsResponse)
def incidents_by_status(session: Session = Depends(get_db_session)) -> AnalyticsBucketsResponse:
    return FleetQueryService(session).analytics_incidents_by_status()


@router.get("/incidents/by-site", response_model=AnalyticsBucketsResponse)
def incidents_by_site(session: Session = Depends(get_db_session)) -> AnalyticsBucketsResponse:
    return FleetQueryService(session).analytics_incidents_by_site()


@router.get("/incidents/trend", response_model=AnalyticsTrendResponse)
def incident_trend(session: Session = Depends(get_db_session)) -> AnalyticsTrendResponse:
    return FleetQueryService(session).analytics_incident_trend()
