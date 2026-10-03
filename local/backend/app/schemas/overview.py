"""Configured local-machine overview contract.

The overview deliberately exposes only backend-owned canonical facts for the
configured edge machine. It contains no fleet totals, inferred health score,
uptime/productivity estimate, prediction, or guessed connectivity state.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import OperatingSessionState, ReturnToServiceState
from app.schemas.assets import MachineResponse
from app.schemas.return_to_service import ReturnToServiceBlockingReason
from app.schemas.sessions import OperatingSessionResponse


class LocalOverviewCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    components: int = Field(ge=0)
    evidence: int = Field(ge=0)
    incidents: int = Field(ge=0)
    incidents_by_status: dict[str, int]


class LocalReturnToServiceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ReturnToServiceState
    blocking_reasons: list[ReturnToServiceBlockingReason]
    policy_identifier: str
    policy_revision: int


class LocalSyncTransportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport_configured: bool
    transport_available: bool | None = None
    transport_checked_at: datetime | None = None
    latest_package_state: str | None = None
    last_acknowledgement: datetime | None = None
    last_error: str | None = None


class OverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    demo_mode: bool = False
    machine: MachineResponse
    active_session: OperatingSessionResponse | None = None
    operating_state: OperatingSessionState | None = None
    unresolved_incident_count: int = Field(ge=0)
    counts: LocalOverviewCounts
    return_to_service: LocalReturnToServiceSummary
    sync: LocalSyncTransportSummary
