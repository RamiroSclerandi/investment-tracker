import asyncio
from typing import Literal

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from investment_tracker.core.errors import DomainError

logger = structlog.get_logger()

router = APIRouter(tags=["ops"])


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
