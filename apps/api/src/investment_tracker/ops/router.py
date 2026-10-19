import asyncio
from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from investment_tracker.core.errors import DomainError
from investment_tracker.core.rate_limit import client_ip_key

logger = structlog.get_logger()

router = APIRouter(tags=["ops"])

CLIENT_IP_HEADERS = (
    "cf-connecting-ip",
    "true-client-ip",
    "x-forwarded-for",
    "x-real-ip",
    "x-vercel-forwarded-for",
    "forwarded",
)


class DatabaseUnavailableError(DomainError):
    code = "DATABASE_UNAVAILABLE"
    status = 503
    title = "Service unavailable"

    def __init__(self) -> None:
        super().__init__("The database is not reachable.")


class HealthStatus(BaseModel):
    status: Literal["ok", "ready"]


@router.get("/healthz")
async def healthz() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get("/readyz")
async def readyz(request: Request) -> HealthStatus:
    timeout = request.app.state.settings.readyz_timeout_seconds
    try:
        async with asyncio.timeout(timeout), request.app.state.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        # Only the exception type is logged: driver messages can embed connection details.
        logger.warning("readiness_check_failed", error_type=type(exc).__name__)
        raise DatabaseUnavailableError from None
    return HealthStatus(status="ready")


class ClientIpDebug(BaseModel):
    rate_limit_key: str
    headers: dict[str, str | None]


@router.get("/ops/client-ip-debug", include_in_schema=False)
async def client_ip_debug(request: Request, response: Response) -> ClientIpDebug:
    response.headers["Cache-Control"] = "no-store"
    return ClientIpDebug(
        rate_limit_key=client_ip_key(request),
        headers={name: request.headers.get(name) for name in CLIENT_IP_HEADERS},
    )
