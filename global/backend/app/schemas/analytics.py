"""Relational-only fleet analytics contracts."""

from pydantic import BaseModel, ConfigDict


class AnalyticsSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machines: int
    sessions: int
    incidents: int
    unresolved_incidents: int
    evidence: int
    maintenance_actions: int
    verification_runs: int
    completed_verification_runs: int
    verification_completion_rate: float | None = None
    sync_conflicts_unresolved: int


class AnalyticsCountBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    count: int


class AnalyticsBucketsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AnalyticsCountBucket]


class AnalyticsTrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: str
    count: int


class AnalyticsTrendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AnalyticsTrendPoint]
