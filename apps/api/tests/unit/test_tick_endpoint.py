import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app
from investment_tracker.market.cadence import Fetcher
from investment_tracker.market.events import PriceEvents
from investment_tracker.market.models import JobRunStatus
from investment_tracker.market.router import get_tick_service
from investment_tracker.market.tick import FetcherOutcome

SECRET = "s" * 32
TICK = "/api/v1/internal/jobs/tick"


class FakeTick:
    def __init__(self) -> None:
        self.runs = 0

    async def run(self) -> list[FetcherOutcome]:
        self.runs += 1
        return [
            FetcherOutcome(Fetcher.CRYPTO_LIVE, JobRunStatus.PARTIAL, items_ok=2, items_failed=1),
            FetcherOutcome(Fetcher.MEP, JobRunStatus.NOT_DUE),
        ]


def _app(job_secret: str | None) -> tuple[FastAPI, FakeTick]:
    settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test"),
        job_secret=SecretStr(job_secret) if job_secret else None,
    )
    app = create_app(settings)
    tick = FakeTick()
    app.dependency_overrides[get_tick_service] = lambda: tick
    return app, tick


@pytest.fixture
async def secured() -> AsyncIterator[tuple[httpx.AsyncClient, FakeTick]]:
    app, tick = _app(SECRET)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, tick


async def test_the_tick_runs_with_the_job_secret_and_reports_each_fetcher(
    secured: tuple[httpx.AsyncClient, FakeTick],
) -> None:
    client, tick = secured

    response = await client.post(TICK, headers={"X-Job-Secret": SECRET})

    assert response.status_code == 200
    assert response.json() == {
        "fetchers": [
            {"fetcher": "crypto_live", "status": "PARTIAL", "items_ok": 2, "items_failed": 1},
            {"fetcher": "mep", "status": "NOT_DUE", "items_ok": 0, "items_failed": 0},
        ]
    }
    assert tick.runs == 1


@pytest.mark.parametrize("headers", [{}, {"X-Job-Secret": "wrong"}, {"X-Job-Secret": SECRET[:-1]}])
async def test_the_tick_rejects_a_missing_or_wrong_secret(
    secured: tuple[httpx.AsyncClient, FakeTick], headers: dict[str, str]
) -> None:
    client, tick = secured

    response = await client.post(TICK, headers=headers)

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_JOB_SECRET"
    assert tick.runs == 0


async def test_the_tick_is_closed_when_no_job_secret_is_configured() -> None:
    app, tick = _app(None)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(TICK, headers={"X-Job-Secret": ""})

    assert response.status_code == 401
    assert tick.runs == 0


def test_a_short_job_secret_is_rejected() -> None:
    with pytest.raises(ValueError, match="job_secret"):
        Settings(
            database_url=SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test"),
            job_secret=SecretStr("short"),
        )


def test_the_tick_is_not_part_of_the_public_schema() -> None:
    app, _ = _app(SECRET)

    assert TICK not in app.openapi()["paths"]


def test_a_blank_job_secret_counts_as_unset() -> None:
    settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test"),
        job_secret=SecretStr(""),
    )

    assert settings.job_secret is None


def test_a_failing_price_handler_does_not_stop_the_others() -> None:
    events = PriceEvents()
    received: list[frozenset[uuid.UUID]] = []

    def broken(_: frozenset[uuid.UUID]) -> None:
        raise RuntimeError("consumer down")

    events.subscribe(broken)
    events.subscribe(received.append)
    asset_ids = frozenset({uuid.uuid4()})

    events.publish(asset_ids)

    assert received == [asset_ids]
