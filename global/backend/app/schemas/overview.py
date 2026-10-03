"""Authoritative global dashboard summary contracts."""

from pydantic import BaseModel, ConfigDict


class OverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machines_total: int
    components_total: int
    incidents_total: int
    incidents_by_status: dict[str, int]
