"""The error contract: every error response has the same JSON shape.

{"error": {"code": ..., "message": ..., "request_id": ..., "details": [...]}}
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from leavedesk.db.errors import sqlstate
from leavedesk.domain.exceptions import (
    InsufficientBalanceError,
    InvalidLeaveRequestError,
    InvalidTransitionError,
    LeaveDeskError,
    NotAuthorizedError,
    NotFoundError,
    OverlappingLeaveError,
    PolicyViolationError,
    VersionConflictError,
)

logger = logging.getLogger("leavedesk.api")

# Domain error -> (HTTP status, error code). Checked in order, so the base
# class LeaveDeskError must stay last.
DOMAIN_ERRORS: list[tuple[type[LeaveDeskError], int, str]] = [
    (NotFoundError, 404, "NOT_FOUND"),
    (NotAuthorizedError, 403, "FORBIDDEN"),
    (OverlappingLeaveError, 409, "OVERLAPPING_LEAVE"),
    (InvalidTransitionError, 409, "INVALID_TRANSITION"),
    (VersionConflictError, 409, "VERSION_CONFLICT"),
    (InvalidLeaveRequestError, 422, "VALIDATION_ERROR"),
    (PolicyViolationError, 422, "POLICY_VIOLATION"),
    (InsufficientBalanceError, 422, "INSUFFICIENT_BALANCE"),
    (LeaveDeskError, 400, "BAD_REQUEST"),
]

HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
    503: "TRY_AGAIN",
}


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(
    status: int,
    code: str,
    message: str,
    request_id: str | None,
    details: list[dict] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details or [],
        }
    }
    return JSONResponse(body, status_code=status, headers=headers)


async def handle_domain_error(request: Request, error: LeaveDeskError) -> JSONResponse:
    status, code = next(
        (status, code) for kind, status, code in DOMAIN_ERRORS if isinstance(error, kind)
    )
    details = getattr(error, "details", None) or []
    if status == 422 and not details:
        details = [{"field": None, "problem": str(error)}]
    return error_response(status, code, str(error), request_id_of(request), details)


async def handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    problems = error.errors()
    if any(p.get("type") == "json_invalid" for p in problems):
        return error_response(
            400, "BAD_REQUEST", "the request body is not valid JSON", request_id_of(request)
        )

    details = []
    for problem in problems:
        # loc looks like ("body", "end_date") or ("query", "limit").
        location = [str(part) for part in problem.get("loc", ())[1:]]
        details.append(
            {
                "field": ".".join(location) or None,
                "problem": problem.get("msg", "invalid value").removeprefix("Value error, "),
            }
        )
    return error_response(
        422, "VALIDATION_ERROR", "the request is not valid", request_id_of(request), details
    )


async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    code = HTTP_CODES.get(error.status_code, "HTTP_ERROR")
    message = error.detail if isinstance(error.detail, str) else code.lower()
    return error_response(
        error.status_code,
        code,
        message,
        request_id_of(request),
        headers=getattr(error, "headers", None),
    )


# PostgreSQL errors where trying again a moment later will most likely work.
RETRYABLE_SQLSTATES = {
    "55P03": "a row lock was not free in time (lock_timeout)",
    "57014": "a query took too long (statement_timeout)",
    "40P01": "deadlock",
    "40001": "serialization failure",
}


async def handle_database_error(request: Request, error: DBAPIError) -> JSONResponse:
    code = sqlstate(error)
    if code not in RETRYABLE_SQLSTATES:
        raise error  # unexpected: the middleware logs it and answers 500
    logger.warning("database busy (%s): %s", code, RETRYABLE_SQLSTATES[code])
    return error_response(
        503,
        "TRY_AGAIN",
        "the service is busy; please try again in a moment",
        request_id_of(request),
        headers={"Retry-After": "1"},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LeaveDeskError, handle_domain_error)
    app.add_exception_handler(DBAPIError, handle_database_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
    # Unexpected errors (500) are handled in RequestContextMiddleware, so the
    # response still gets an X-Request-ID header.
