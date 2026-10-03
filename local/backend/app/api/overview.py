from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.overview import OverviewResponse
from app.services.overview import (
    ConfiguredOverviewMachineNotFoundError,
    OverviewConfigurationError,
    OverviewQueryService,
)
from app.services.return_to_service import ReturnToServiceConfigurationError
from app.services.sync import SyncServiceError

router = APIRouter(tags=["Overview"])


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> OverviewResponse:
    try:
        return OverviewQueryService(
            uow_factory_for_session(session), settings
        ).get_overview()
    except (OverviewConfigurationError, ReturnToServiceConfigurationError, SyncServiceError) as exc:
        raise api_error(
            status_code=503,
            code="LOCAL_MACHINE_NOT_CONFIGURED",
            message=str(exc),
        ) from exc
    except ConfiguredOverviewMachineNotFoundError as exc:
        raise api_error(
            status_code=404,
            code="CONFIGURED_MACHINE_NOT_FOUND",
            message=str(exc),
        ) from exc
