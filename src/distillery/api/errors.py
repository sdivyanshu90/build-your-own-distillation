"""Translation of domain exceptions into HTTP responses.

A single, consistent error envelope is returned for every failure::

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}

Unexpected (non-domain) exceptions are logged with a stack trace and reported as
a generic 500 without leaking internals — an OWASP-aligned default.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from distillery.domain.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DistilleryError,
    EntityNotFoundError,
    QuotaExceededError,
    TeacherError,
    TrainingError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Map domain exception classes to HTTP status codes.
_STATUS_MAP: list[tuple[type[DistilleryError], int]] = [
    (ValidationError, status.HTTP_400_BAD_REQUEST),
    (AuthenticationError, status.HTTP_401_UNAUTHORIZED),
    (AuthorizationError, status.HTTP_403_FORBIDDEN),
    (EntityNotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),
    (QuotaExceededError, status.HTTP_429_TOO_MANY_REQUESTS),
    (TeacherError, status.HTTP_502_BAD_GATEWAY),
    (TrainingError, status.HTTP_500_INTERNAL_SERVER_ERROR),
]


def _status_for(exc: DistilleryError) -> int:
    for exc_type, code in _STATUS_MAP:
        if isinstance(exc, exc_type):
            return code
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _envelope(exc: DistilleryError, request: Request) -> dict:
    body = exc.to_dict()
    body["request_id"] = getattr(request.state, "request_id", None)
    return {"error": body}


def install_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers on the FastAPI app."""

    @app.exception_handler(DistilleryError)
    async def _domain_handler(request: Request, exc: DistilleryError) -> JSONResponse:
        http_status = _status_for(exc)
        if http_status >= 500:
            logger.error("Domain error %s: %s", exc.code, exc.message)
        return JSONResponse(status_code=http_status, content=_envelope(exc, request))

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "request_validation_error",
                    "message": "Request validation failed.",
                    "details": {"errors": _safe_errors(exc)},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An internal error occurred.",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )


def _safe_errors(exc: RequestValidationError) -> list[dict]:
    """Strip non-serialisable context from pydantic validation errors."""
    cleaned: list[dict] = []
    for err in exc.errors():
        cleaned.append(
            {
                "loc": [str(p) for p in err.get("loc", [])],
                "msg": err.get("msg"),
                "type": err.get("type"),
            }
        )
    return cleaned
