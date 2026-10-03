"""Shared HTTP transport schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
    # Retained for compatibility with earlier clients/tests that consumed FastAPI's
    # ``detail`` field directly. New clients should use ``error``.
    detail: Any | None = None
