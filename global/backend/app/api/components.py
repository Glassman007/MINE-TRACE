from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import uow_factory_for_session
from app.api.errors import api_error
from app.db.session import get_db_session
from app.schemas.assets import ComponentResponse
from app.services.assets import AssetQueryService, UnknownComponentAssetError

router = APIRouter(prefix="/components", tags=["Components"])


@router.get("/{component_id}", response_model=ComponentResponse)
def get_component(
    component_id: UUID, session: Session = Depends(get_db_session)
) -> ComponentResponse:
    try:
        return AssetQueryService(uow_factory_for_session(session)).get_component(component_id)
    except UnknownComponentAssetError as exc:
        raise api_error(status_code=404, code="COMPONENT_NOT_FOUND", message=str(exc)) from exc
