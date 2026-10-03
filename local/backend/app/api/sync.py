from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.sync import SyncStatusResponse
from app.services.sync import SyncServiceError, SyncStatusService

router = APIRouter(prefix="/sync", tags=["Sync"])


@router.get("/status", response_model=SyncStatusResponse, response_model_exclude_none=True)
def get_sync_status(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SyncStatusResponse:
    try:
        return SyncStatusService(
            uow_factory_for_session(session), settings
        ).get_status()
    except SyncServiceError as exc:
        raise api_error(
            status_code=503,
            code="SYNC_CONFIGURATION_ERROR",
            message=str(exc),
        ) from exc
