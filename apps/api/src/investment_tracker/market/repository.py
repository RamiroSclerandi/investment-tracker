import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession

from investment_tracker.market.catalog import SeedAsset
from investment_tracker.market.models import (
    Asset,
    AssetPrice,
    FxLatest,
    FxRate,
    FxRateType,
    JobRun,
    JobRunStatus,
    LatestPrice,
    MarketHoliday,
)

CATALOG_FIELDS = (
    "type",
    "symbol",
    "name",
    "quote_currency",
    "price_factor",
    "maturity_date",
    "fci_category",
    "live_provider",
)


@dataclass(frozen=True)
class UpsertCounts:
    inserted: int
    updated: int


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_catalog(self, assets: Sequence[SeedAsset]) -> UpsertCounts:
        if not assets:
            return UpsertCounts(0, 0)
        rows = [asset.model_dump() | {"is_tracked": True} for asset in assets]
        values = insert(Asset).values(rows)
        results: Sequence[bool] = (
            await self._session.scalars(
                values.on_conflict_do_update(
                    index_elements=[Asset.provider, Asset.provider_ref],
                    set_={field: values.excluded[field] for field in CATALOG_FIELDS}
                    | {"updated_at": func.now()},
                ).returning(literal_column("xmax = 0"))
            )
        ).all()
        inserted = sum(1 for was_inserted in results if was_inserted)
        return UpsertCounts(inserted, len(results) - inserted)


@dataclass(frozen=True)
class PriceWrite:
    asset_id: uuid.UUID
    price: Decimal


class MarketDataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def holidays_between(self, start: date, end: date) -> frozenset[date]:
        days = await self._session.scalars(
            select(MarketHoliday.day).where(MarketHoliday.day.between(start, end))
        )
        return frozenset(days)

    async def last_successes(self, jobs: Collection[str]) -> dict[str, datetime]:
        rows = await self._session.execute(
            select(JobRun.job, func.max(JobRun.started_at))
            .where(
                JobRun.job.in_(jobs),
                JobRun.status.in_([JobRunStatus.OK, JobRunStatus.PARTIAL]),
            )
            .group_by(JobRun.job)
        )
        return {job: started_at for job, started_at in rows.tuples()}

    async def tracked_assets(self) -> list[Asset]:
        return list(await self._session.scalars(select(Asset).where(Asset.is_tracked)))

    async def try_lock(self, key: str) -> bool:
        acquired = await self._session.scalar(
            select(func.pg_try_advisory_xact_lock(func.hashtextextended(key, 0)))
        )
        return bool(acquired)

    async def save_prices(
        self, prices: Sequence[PriceWrite], ts: datetime, bucket: datetime, source: str
    ) -> None:
        if not prices:
            return
        latest = insert(LatestPrice).values(
            [{"asset_id": p.asset_id, "price": p.price, "ts": ts, "source": source} for p in prices]
        )
        await self._session.execute(
            latest.on_conflict_do_update(
                index_elements=[LatestPrice.asset_id],
                set_=_excluded(latest, "price", "ts", "source"),
            )
        )
        buckets = insert(AssetPrice).values(
            [
                {"asset_id": p.asset_id, "bucket": bucket, "price": p.price, "source": source}
                for p in prices
            ]
        )
        await self._session.execute(
            buckets.on_conflict_do_update(
                index_elements=[AssetPrice.asset_id, AssetPrice.bucket],
                set_=_excluded(buckets, "price", "source"),
            )
        )

    async def save_fx(
        self, rate_type: FxRateType, buy: Decimal, sell: Decimal, ts: datetime, bucket: datetime
    ) -> None:
        latest = insert(FxLatest).values(rate_type=rate_type, buy=buy, sell=sell, ts=ts)
        await self._session.execute(
            latest.on_conflict_do_update(
                index_elements=[FxLatest.rate_type], set_=_excluded(latest, "buy", "sell", "ts")
            )
        )
        hourly = insert(FxRate).values(rate_type=rate_type, ts=bucket, buy=buy, sell=sell)
        await self._session.execute(
            hourly.on_conflict_do_update(
                index_elements=[FxRate.rate_type, FxRate.ts], set_=_excluded(hourly, "buy", "sell")
            )
        )

    def add_run(self, run: JobRun) -> None:
        self._session.add(run)


def _excluded(statement: Insert, *fields: str) -> dict[str, object]:
    return {field: statement.excluded[field] for field in fields} | {"updated_at": func.now()}
