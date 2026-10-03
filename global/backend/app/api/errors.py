"""Consistent transport error handling for the FastAPI layer."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def api_error(*, status_code: int, code: str, message: str, details: Any | None = None) -> APIError:
    return APIError(status_code=status_code, code=code, message=message, details=details)


def _payload(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details},
        "detail": message if details is None else details,
    }


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(_request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(_payload(exc.code, exc.message, exc.details)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = exc.errors()
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(_payload("VALIDATION_ERROR", "Request validation failed", details)),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == 404:
            code = "NOT_FOUND"
            message = "Resource not found"
        else:
            code = "HTTP_ERROR"
            message = str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(_payload(code, message, exc.detail)),
            headers=exc.headers,
        )
