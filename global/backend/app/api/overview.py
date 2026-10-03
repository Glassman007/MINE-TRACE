from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.db.session import get_db_session
from app.schemas.overview import OverviewResponse
from app.services.overview import OverviewQueryService

router = APIRouter(tags=["Overview"])


@router.get("/overview", response_model=OverviewResponse)
def get_overview(session: Session = Depends(get_db_session)) -> OverviewResponse:
    return OverviewQueryService(uow_factory_for_session(session)).get_overview()
