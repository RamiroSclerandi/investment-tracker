import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from investment_tracker.core.errors import DomainError
from investment_tracker.market.cadence import Fetcher
from investment_tracker.market.calendar import MarketHours
from investment_tracker.market.models import JobRunStatus
from investment_tracker.market.tick import FetcherOutcome, TickService


class InvalidJobSecretError(DomainError):
    code = "INVALID_JOB_SECRET"
    status = 401
    title = "Invalid job secret"

    def __init__(self) -> None:
        super().__init__("A valid X-Job-Secret header is required.")


def require_job_secret(request: Request, x_job_secret: Annotated[str, Header()] = "") -> None:
    secret = request.app.state.settings.job_secret
    if secret is None or not hmac.compare_digest(
        x_job_secret.encode(), secret.get_secret_value().encode()
    ):
        raise InvalidJobSecretError


def get_tick_service(request: Request) -> TickService:
    settings = request.app.state.settings
    return TickService(
        request.app.state.sessionmaker,
        request.app.state.providers,
        MarketHours(settings.market_open, settings.market_close),
        request.app.state.price_events,
    )


class FetcherResult(BaseModel):
    fetcher: Fetcher
    status: JobRunStatus
    items_ok: int
    items_failed: int


class TickResponse(BaseModel):
    fetchers: list[FetcherResult]


router = APIRouter(
    prefix="/internal/jobs",
    tags=["internal"],
    include_in_schema=False,
    dependencies=[Depends(require_job_secret)],
)


@router.post("/tick")
async def run_tick(tick: Annotated[TickService, Depends(get_tick_service)]) -> TickResponse:
    outcomes: list[FetcherOutcome] = await tick.run()
    return TickResponse(
        fetchers=[
            FetcherResult(
                fetcher=o.fetcher,
                status=o.status,
                items_ok=o.items_ok,
                items_failed=o.items_failed,
            )
            for o in outcomes
        ]
    )
