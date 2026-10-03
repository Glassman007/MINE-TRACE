"""Transport contracts for controlled machine/component identity reads."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MachineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    display_name: str | None = None
    asset_code: str | None = None
    machine_type: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    site_name: str | None = None
    site_area: str | None = None


class MachineCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MachineResponse]
    total: int
    offset: int
    limit: int


class ComponentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    machine_id: UUID
    display_name: str | None = None
    component_type: str | None = None
    manufacturer: str | None = None
    model: str | None = None


class MachineComponentsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: UUID
    components: list[ComponentResponse]
