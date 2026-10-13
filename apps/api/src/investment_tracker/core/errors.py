from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-ID"

logger = structlog.get_logger()


class DomainError(Exception):
    code = "DOMAIN_ERROR"
    status = 400
    title = "Domain error"


def problem_response(
    request: Request,
    *,
    status: int,
    title: str,
    detail: str,
    code: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = request.scope.get("state", {}).get("request_id", "")
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": request_id,
        **(extra or {}),
    }
    return JSONResponse(
        body,
        status_code=status,
        media_type=PROBLEM_CONTENT_TYPE,
        headers={REQUEST_ID_HEADER: request_id},
    )


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):
        raise exc
    return problem_response(
        request, status=exc.status, title=exc.title, detail=str(exc), code=exc.code
    )


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        title="HTTP error",
        detail=str(exc.detail),
        code=f"HTTP_{exc.status_code}",
    )


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    errors = [{"loc": list(error["loc"]), "msg": error["msg"]} for error in exc.errors()]
    return problem_response(
        request,
        status=422,
        title="Validation error",
        detail="The request is invalid.",
        code="VALIDATION_ERROR",
        extra={"errors": errors},
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Contextvars are already unbound here: this handler runs outside the request-id middleware.
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        request_id=request.scope.get("state", {}).get("request_id", ""),
        exc_info=exc,
    )
    return problem_response(
        request,
        status=500,
        title="Internal server error",
        detail="An unexpected error occurred.",
        code="INTERNAL_ERROR",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
