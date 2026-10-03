"""Deterministic configured-machine return-to-service endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.return_to_service import ReturnToServiceResponse
from app.services.return_to_service import (
    ReturnToServiceConfigurationError,
    ReturnToServiceService,
)

router = APIRouter(tags=["Return to Service"])


@router.get("/return-to-service", response_model=ReturnToServiceResponse)
def get_return_to_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ReturnToServiceResponse:
    try:
        return ReturnToServiceService(
            settings, uow_factory_for_session(session)
        ).evaluate()
    except ReturnToServiceConfigurationError as exc:
        raise api_error(
            status_code=409,
            code="LOCAL_MACHINE_NOT_CONFIGURED",
            message=str(exc),
        ) from exc
