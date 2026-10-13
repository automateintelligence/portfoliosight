"""The error envelope ``{"error": {"code", "message", "details"}}`` and its handlers (spec 6)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from portfoliosight.data.secrets import install_redaction, redacted_traceback

logger = logging.getLogger(__name__)
install_redaction([logger.name])

NO_STORE = {"Cache-Control": "no-store"}
_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


class ApiError(Exception):
    """A refusal with its HTTP status and envelope fields."""

    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def error_response(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details}}
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def forbidden() -> JSONResponse:
    """The gate's refusal; it says nothing about the value that was sent or expected."""
    return error_response(403, "forbidden", "This service is not open to direct requests.")


def invalid_request(message: str, details: Any = None) -> ApiError:
    return ApiError(422, "invalid_request", message, details)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Only where the request failed and why: the offending input is not echoed.
        problems = [
            {"where": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
            for error in exc.errors()
        ]
        return error_response(422, "invalid_request", "The request is not valid.", problems)


def unexpected_error(exc: Exception) -> JSONResponse:
    """The answer to a failure nothing else handled: logged here, redacted, and not re-raised.

    An exception that left the application would be printed by the server with its message and
    traceback as they are; this keeps a credential an error text may carry out of the log.
    """
    logger.error("unhandled error\n%s", redacted_traceback(exc))
    return error_response(500, "internal_error", "The service could not answer.")
