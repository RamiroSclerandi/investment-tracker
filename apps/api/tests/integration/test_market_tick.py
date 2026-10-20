import asyncio
import dataclasses
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from investment_tracker.auth.models import Currency
from investment_tracker.core.db import create_sessionmaker
from investment_tracker.market.cadence import Fetcher
from investment_tracker.market.calendar import MarketHours
from investment_tracker.market.events import PriceEvents
from investment_tracker.market.models import JobRunStatus
from investment_tracker.market.providers.base import FxQuote, PricePoint, ProviderError
from investment_tracker.market.providers.registry import ProviderRegistry, build_registry
from investment_tracker.market.tick import TickService

pytestmark = pytest.mark.integration

MONDAY_NOON_ART = datetime(2026, 10, 19, 15, 0, 30, tzinfo=UTC)
SUNDAY_NOON_ART = datetime(2026, 10, 18, 15, 0, 30, tzinfo=UTC)
HOURS = MarketHours(time(11), time(17))


class FakePrices:
    def __init__(
        self, name: str, prices: dict[str, Decimal], *, error: str | None = None, delay: float = 0
    ) -> None:
        self.name = name
        self._prices = prices
        self._error = error
        self._delay = delay

    async def latest(self, refs: Sequence[str]) -> dict[str, PricePoint]:
        await asyncio.sleep(self._delay)
        if self._error:
            raise ProviderError(self.name, self._error)
        return {
            ref: PricePoint(
                symbol=ref, price=self._prices[ref], currency=Currency.USD, fetched_at=NOW
            )
            for ref in refs
            if ref in self._prices
        }

    async def history(self, ref: str, start: date, end: date) -> list[PricePoint]:
        raise NotImplementedError


class FakeMep:
    def __init__(self, name: str, quote: tuple[str, str] | None) -> None:
        self.name = name
        self._quote = quote

    async def latest(self) -> FxQuote:
        if self._quote is None:
            raise ProviderError(self.name, "down")
        buy, sell = self._quote
        return FxQuote(buy=Decimal(buy), sell=Decimal(sell), source_ts=None, fetched_at=NOW)


NOW = MONDAY_NOON_ART


@pytest.fixture
async def owner_engine(owner_database_url: str) -> AsyncIterator[AsyncEngine]:
    db_engine = create_async_engine(owner_database_url)
    async with db_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE app.job_runs, app.latest_prices, app.asset_prices, app.fx_latest,"
                " app.fx_rates, app.market_holidays, app.assets CASCADE"
            )
        )
    yield db_engine
    await db_engine.dispose()


@pytest.fixture
async def sessionmaker(
    migrated_database_url: str, owner_engine: AsyncEngine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_engine = create_async_engine(migrated_database_url)
    yield create_sessionmaker(db_engine)
    await db_engine.dispose()


@pytest.fixture
async def assets(owner_engine: AsyncEngine) -> dict[str, uuid.UUID]:
    rows = {
        "BTC": ("CRYPTO", "USD", "coingecko", "bitcoin", "kraken", True),
        "ETH": ("CRYPTO", "USD", "coingecko", "ethereum", "kraken", True),
        "AL30": ("SOV_BONDS", "ARS", "data912", "arg_bonds/AL30", None, True),
        "GGAL": ("STOCK_AR", "ARS", "data912", "arg_stocks/GGAL", None, False),
    }
    ids: dict[str, uuid.UUID] = {}
    async with owner_engine.begin() as connection:
        for symbol, (kind, currency, provider, ref, live, tracked) in rows.items():
            ids[symbol] = await connection.scalar(
                text(
                    "INSERT INTO app.assets (type, symbol, name, quote_currency, provider,"
                    " provider_ref, live_provider, is_tracked) VALUES (:type, :symbol, :symbol,"
                    " :currency, :provider, :ref, :live, :tracked) RETURNING id"
                ),
                {
                    "type": kind,
                    "symbol": symbol,
                    "currency": currency,
                    "provider": provider,
                    "ref": ref,
                    "live": live,
                    "tracked": tracked,
                },
            )
    return ids


def _registry(**overrides: Any) -> ProviderRegistry:
    defaults: dict[str, Any] = {
        "crypto_live": FakePrices("kraken", {"BTC": Decimal("81970.7"), "ETH": Decimal("2500")}),
        "prices": FakePrices("data912", {"arg_bonds/AL30": Decimal("85200")}),
        "mep": FakeMep("dolarapi", ("1530", "1540")),
        "mep_fallback": FakeMep("data912", ("1520", "1545")),
    }
    return dataclasses.replace(build_registry(httpx.AsyncClient()), **(defaults | overrides))


def _tick(
    sessionmaker: async_sessionmaker[AsyncSession],
    now: datetime = NOW,
    events: PriceEvents | None = None,
    budget: float = 20.0,
    **providers: Any,
) -> TickService:
    return TickService(
        sessionmaker,
        _registry(**providers),
        HOURS,
        events or PriceEvents(),
        now=lambda: now,
        budget_seconds=budget,
    )


async def _rows(engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as connection:
        return list((await connection.execute(text(sql), params)).all())


async def test_a_tick_in_market_hours_runs_every_fetcher_and_stores_latest_and_hour_buckets(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    published: list[frozenset[uuid.UUID]] = []
    events = PriceEvents()
    events.subscribe(published.append)

    outcomes = await _tick(sessionmaker, events=events).run()

    assert {(o.fetcher, o.status, o.items_ok, o.items_failed) for o in outcomes} == {
        (Fetcher.CRYPTO_LIVE, JobRunStatus.OK, 2, 0),
        (Fetcher.AR_LIVE, JobRunStatus.OK, 1, 0),
        (Fetcher.MEP, JobRunStatus.OK, 1, 0),
    }
    latest = await _rows(owner_engine, "SELECT asset_id, price, ts, source FROM app.latest_prices")
    assert {(r.asset_id, r.price, r.ts, r.source) for r in latest} == {
        (assets["BTC"], Decimal("81970.7"), NOW, "kraken"),
        (assets["ETH"], Decimal("2500"), NOW, "kraken"),
        (assets["AL30"], Decimal("85200"), NOW, "data912"),
    }
    buckets = await _rows(owner_engine, "SELECT asset_id, bucket FROM app.asset_prices")
    assert {r.bucket for r in buckets} == {datetime(2026, 10, 19, 15, tzinfo=UTC)}
    assert len(buckets) == 3
    fx = await _rows(owner_engine, "SELECT buy, sell, mid, ts FROM app.fx_latest")
    assert [(r.buy, r.sell, r.mid, r.ts) for r in fx] == [
        (Decimal("1530"), Decimal("1540"), Decimal("1535"), NOW)
    ]
    fx_buckets = await _rows(owner_engine, "SELECT ts FROM app.fx_rates")
    assert [r.ts for r in fx_buckets] == [datetime(2026, 10, 19, 15, tzinfo=UTC)]
    runs = await _rows(owner_engine, "SELECT job, status, started_at FROM app.job_runs")
    assert {(r.job, r.status, r.started_at) for r in runs} == {
        ("crypto_live", "OK", NOW),
        ("ar_live", "OK", NOW),
        ("mep", "OK", NOW),
    }
    assert published == [frozenset({assets["BTC"], assets["ETH"], assets["AL30"]})]


async def test_a_repeated_tick_before_the_cadence_runs_nothing_and_writes_nothing(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    await _tick(sessionmaker).run()

    outcomes = await _tick(sessionmaker, now=NOW + timedelta(seconds=30)).run()

    assert {o.status for o in outcomes} == {JobRunStatus.NOT_DUE}
    assert len(await _rows(owner_engine, "SELECT id FROM app.job_runs")) == 3


async def test_a_later_tick_in_the_same_hour_updates_the_bucket_instead_of_adding_one(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    await _tick(sessionmaker).run()
    later = NOW + timedelta(minutes=1)
    crypto = FakePrices("kraken", {"BTC": Decimal("82000"), "ETH": Decimal("2500")})

    await _tick(sessionmaker, now=later, crypto_live=crypto).run()

    rows = await _rows(
        owner_engine,
        "SELECT price FROM app.asset_prices WHERE asset_id = :id",
        id=assets["BTC"],
    )
    assert [r.price for r in rows] == [Decimal("82000")]
    latest = await _rows(
        owner_engine,
        "SELECT price, ts FROM app.latest_prices WHERE asset_id = :id",
        id=assets["BTC"],
    )
    assert [(r.price, r.ts) for r in latest] == [(Decimal("82000"), later)]


async def test_only_crypto_runs_while_the_market_is_closed(
    sessionmaker: async_sessionmaker[AsyncSession], assets: dict[str, uuid.UUID]
) -> None:
    outcomes = await _tick(sessionmaker, now=SUNDAY_NOON_ART).run()

    assert {o.fetcher: o.status for o in outcomes} == {
        Fetcher.CRYPTO_LIVE: JobRunStatus.OK,
        Fetcher.AR_LIVE: JobRunStatus.NOT_DUE,
        Fetcher.MEP: JobRunStatus.NOT_DUE,
    }


async def test_a_weekday_holiday_closes_the_market(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO app.market_holidays (date, kind, name)"
                " VALUES ('2026-10-19', 'trasladable', 'Diversidad Cultural')"
            )
        )

    outcomes = await _tick(sessionmaker).run()

    assert {o.fetcher for o in outcomes if o.status != JobRunStatus.NOT_DUE} == {
        Fetcher.CRYPTO_LIVE
    }


async def test_a_failed_fetcher_is_recorded_and_retried_on_the_next_tick(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    broken = FakePrices("data912", {}, error="answered HTTP 503")

    outcomes = await _tick(sessionmaker, prices=broken).run()
    retry = await _tick(sessionmaker, now=NOW + timedelta(seconds=30)).run()

    assert {o.fetcher: o.status for o in outcomes}[Fetcher.AR_LIVE] == JobRunStatus.FAILED
    assert {o.fetcher: o.status for o in retry}[Fetcher.AR_LIVE] == JobRunStatus.OK
    errors = await _rows(owner_engine, "SELECT error FROM app.job_runs WHERE status = 'FAILED'")
    assert [r.error for r in errors] == ["data912: answered HTTP 503"]


async def test_missing_quotes_make_a_partial_run(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    crypto = FakePrices("kraken", {"BTC": Decimal("81970.7")})

    outcomes = await _tick(sessionmaker, crypto_live=crypto).run()

    crypto_run = next(o for o in outcomes if o.fetcher == Fetcher.CRYPTO_LIVE)
    assert (crypto_run.status, crypto_run.items_ok, crypto_run.items_failed) == (
        JobRunStatus.PARTIAL,
        1,
        1,
    )


async def test_prices_are_rounded_to_the_column_scale_and_a_zero_after_rounding_is_dropped(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    crypto = FakePrices(
        "kraken", {"BTC": Decimal("1.000000000049"), "ETH": Decimal("0.00000000001")}
    )

    outcomes = await _tick(sessionmaker, crypto_live=crypto).run()

    crypto_run = next(o for o in outcomes if o.fetcher == Fetcher.CRYPTO_LIVE)
    assert (crypto_run.items_ok, crypto_run.items_failed) == (1, 1)
    latest = await _rows(
        owner_engine,
        "SELECT price FROM app.latest_prices WHERE asset_id = :id",
        id=assets["BTC"],
    )
    assert [r.price for r in latest] == [Decimal("1.0000000000")]


async def test_the_mep_falls_back_to_data912_when_dolarapi_fails(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    outcomes = await _tick(sessionmaker, mep=FakeMep("dolarapi", None)).run()

    assert {o.fetcher: o.status for o in outcomes}[Fetcher.MEP] == JobRunStatus.OK
    fx = await _rows(owner_engine, "SELECT buy, sell FROM app.fx_latest")
    assert [(r.buy, r.sell) for r in fx] == [(Decimal("1520"), Decimal("1545"))]
    runs = await _rows(owner_engine, "SELECT meta FROM app.job_runs WHERE job = 'mep'")
    assert [r.meta for r in runs] == [{"source": "data912"}]


async def test_a_mep_buy_that_rounds_to_zero_fails_the_run(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    mep = FakeMep("dolarapi", ("0.0000004", "1540"))

    outcomes = await _tick(sessionmaker, mep=mep).run()

    assert {o.fetcher: o.status for o in outcomes}[Fetcher.MEP] == JobRunStatus.FAILED
    assert await _rows(owner_engine, "SELECT rate_type FROM app.fx_latest") == []


async def test_a_fetcher_over_the_budget_fails_without_blocking_the_others(
    sessionmaker: async_sessionmaker[AsyncSession], assets: dict[str, uuid.UUID]
) -> None:
    slow = FakePrices("data912", {"arg_bonds/AL30": Decimal("1")}, delay=1)

    outcomes = await _tick(sessionmaker, budget=0.2, prices=slow).run()

    statuses = {o.fetcher: o.status for o in outcomes}
    assert statuses[Fetcher.AR_LIVE] == JobRunStatus.FAILED
    assert statuses[Fetcher.CRYPTO_LIVE] == JobRunStatus.OK


async def test_a_fetcher_whose_lock_is_held_is_skipped(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    assets: dict[str, uuid.UUID],
) -> None:
    async with owner_engine.connect() as holder, holder.begin():
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('market-tick:crypto_live', 0))")
        )

        outcomes = await _tick(sessionmaker).run()

    assert {o.fetcher: o.status for o in outcomes}[Fetcher.CRYPTO_LIVE] == (
        JobRunStatus.SKIPPED_LOCKED
    )
    latest = await _rows(
        owner_engine,
        "SELECT price FROM app.latest_prices WHERE asset_id = :id",
        id=assets["BTC"],
    )
    assert latest == []
