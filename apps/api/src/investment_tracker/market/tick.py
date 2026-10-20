import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_tracker.market.cadence import Fetcher, due_fetchers
from investment_tracker.market.calendar import ART, MarketHours
from investment_tracker.market.events import PriceEvents
from investment_tracker.market.models import Asset, FxRateType, JobRun, JobRunStatus
from investment_tracker.market.providers.base import (
    Clock,
    FxQuote,
    PriceProvider,
    ProviderError,
    utc_now,
)
from investment_tracker.market.providers.registry import ProviderRegistry
from investment_tracker.market.repository import MarketDataRepository, PriceWrite

BUDGET_SECONDS = 20.0
LOCK_PREFIX = "market-tick"
PRICE_STEP = Decimal("1E-10")
FX_STEP = Decimal("1E-6")
# NUMERIC(30, 10) needs 30 significant digits; the default context keeps 28.
_ROUNDING = Context(prec=40, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class FetcherOutcome:
    fetcher: Fetcher
    status: JobRunStatus
    items_ok: int = 0
    items_failed: int = 0


@dataclass
class _Batch:
    requested: int = 0
    source: str = ""
    prices: list[PriceWrite] = field(default_factory=list)
    fx: FxQuote | None = None
    error: str | None = None
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def items_ok(self) -> int:
        return len(self.prices) + (self.fx is not None)

    @property
    def status(self) -> JobRunStatus:
        if self.error or (self.requested and not self.items_ok):
            return JobRunStatus.FAILED
        return JobRunStatus.PARTIAL if self.items_ok < self.requested else JobRunStatus.OK


class TickService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        providers: ProviderRegistry,
        hours: MarketHours,
        events: PriceEvents,
        *,
        now: Clock = utc_now,
        budget_seconds: float = BUDGET_SECONDS,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._providers = providers
        self._hours = hours
        self._events = events
        self._now = now
        self._budget = budget_seconds

    async def run(self) -> list[FetcherOutcome]:
        now = self._now()
        today = now.astimezone(ART).date()
        async with self._sessionmaker() as session, session.begin():
            repository = MarketDataRepository(session)
            holidays = await repository.holidays_between(today, today)
            last = await repository.last_successes([fetcher.value for fetcher in Fetcher])
            assets = await repository.tracked_assets()
        last_success = {Fetcher(job): started_at for job, started_at in last.items()}
        due = due_fetchers(now, last_success, holidays, self._hours)
        results = await asyncio.gather(*(self._run(fetcher, now, assets) for fetcher in due))
        if any(outcome.status in (JobRunStatus.OK, JobRunStatus.PARTIAL) for outcome, _ in results):
            self._events.publish(frozenset().union(*(ids for _, ids in results)))
        outcomes = {outcome.fetcher: outcome for outcome, _ in results}
        return [outcomes.get(f, FetcherOutcome(f, JobRunStatus.NOT_DUE)) for f in Fetcher]

    async def _run(
        self, fetcher: Fetcher, started_at: datetime, assets: list[Asset]
    ) -> tuple[FetcherOutcome, frozenset[uuid.UUID]]:
        try:
            async with asyncio.timeout(self._budget):
                batch = await self._fetch(fetcher, assets)
        except ProviderError as exc:
            batch = _Batch(error=str(exc))
        except TimeoutError:
            batch = _Batch(error=f"exceeded the {self._budget:g} s tick budget")
        async with self._sessionmaker() as session, session.begin():
            repository = MarketDataRepository(session)
            if not await repository.try_lock(f"{LOCK_PREFIX}:{fetcher}"):
                batch = _Batch()
                status = JobRunStatus.SKIPPED_LOCKED
            else:
                status = batch.status
            if status == JobRunStatus.FAILED:
                batch.prices, batch.fx = [], None
            else:
                await self._save(repository, batch, started_at)
            outcome = FetcherOutcome(
                fetcher, status, batch.items_ok, batch.requested - batch.items_ok
            )
            repository.add_run(
                JobRun(
                    job=fetcher.value,
                    started_at=started_at,
                    finished_at=self._now(),
                    status=status,
                    items_ok=outcome.items_ok,
                    items_failed=outcome.items_failed,
                    error=batch.error or _no_quotes(status),
                    meta=batch.meta,
                )
            )
        return outcome, frozenset(price.asset_id for price in batch.prices)

    async def _save(
        self, repository: MarketDataRepository, batch: _Batch, started_at: datetime
    ) -> None:
        bucket = started_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        await repository.save_prices(batch.prices, started_at, bucket, batch.source)
        if batch.fx is not None:
            await repository.save_fx(
                FxRateType.MEP, batch.fx.buy, batch.fx.sell, started_at, bucket
            )

    async def _fetch(self, fetcher: Fetcher, assets: list[Asset]) -> _Batch:
        match fetcher:
            case Fetcher.CRYPTO_LIVE:
                return await _fetch_prices(self._providers.crypto_live, assets, lambda a: a.symbol)
            case Fetcher.AR_LIVE:
                return await _fetch_prices(self._providers.prices, assets, lambda a: a.provider_ref)
            case Fetcher.MEP:
                return await self._fetch_mep()

    async def _fetch_mep(self) -> _Batch:
        provider = self._providers.mep
        try:
            quote = await provider.latest()
        except ProviderError:
            provider = self._providers.mep_fallback
            quote = await provider.latest()
        buy, sell = (
            value.quantize(FX_STEP, context=_ROUNDING) for value in (quote.buy, quote.sell)
        )
        meta = {"source": provider.name}
        if buy <= 0 or sell < buy:
            return _Batch(
                requested=1, error=f"{provider.name}: invalid MEP quote after rounding", meta=meta
            )
        fx = FxQuote(buy=buy, sell=sell, source_ts=quote.source_ts, fetched_at=quote.fetched_at)
        return _Batch(requested=1, source=provider.name, fx=fx, meta=meta)


def _no_quotes(status: JobRunStatus) -> str | None:
    return "no usable quotes" if status == JobRunStatus.FAILED else None


async def _fetch_prices(
    provider: PriceProvider, assets: list[Asset], ref_of: Callable[[Asset], str]
) -> _Batch:
    ids_by_ref = {
        ref_of(asset): asset.id
        for asset in assets
        if (asset.live_provider or asset.provider) == provider.name
    }
    if not ids_by_ref:
        return _Batch(source=provider.name)
    points = await provider.latest(list(ids_by_ref))
    prices = []
    for ref, point in points.items():
        price = point.price.quantize(PRICE_STEP, context=_ROUNDING)
        if ref in ids_by_ref and price > 0:
            prices.append(PriceWrite(ids_by_ref[ref], price))
    return _Batch(requested=len(ids_by_ref), source=provider.name, prices=prices)
