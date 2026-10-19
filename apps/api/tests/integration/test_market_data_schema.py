import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

pytestmark = pytest.mark.integration


@pytest.fixture
async def app_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    db_engine = create_async_engine(migrated_database_url)
    yield db_engine
    await db_engine.dispose()


async def _insert_asset(engine: AsyncEngine, **overrides: Any) -> uuid.UUID:
    values = {
        "type": "STOCK_AR",
        "symbol": "GGAL",
        "name": "Grupo Financiero Galicia",
        "quote_currency": "ARS",
        "provider": "data912",
        "provider_ref": f"arg_stocks/{uuid.uuid4().hex}",
    } | overrides
    async with engine.begin() as connection:
        asset_id: uuid.UUID = await connection.scalar(
            text(
                "INSERT INTO app.assets"
                " (type, symbol, name, quote_currency, provider, provider_ref)"
                " VALUES (:type, :symbol, :name, :quote_currency, :provider, :provider_ref)"
                " RETURNING id"
            ),
            values,
        )
    return asset_id


async def test_a_new_asset_defaults_to_a_unit_price_factor_and_untracked(
    app_engine: AsyncEngine,
) -> None:
    asset_id = await _insert_asset(app_engine)

    async with app_engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT price_factor, is_tracked, live_provider FROM app.assets WHERE id = :id"
                ),
                {"id": asset_id},
            )
        ).one()

    assert row.price_factor == Decimal(1)
    assert row.is_tracked is False
    assert row.live_provider is None


async def test_two_assets_cannot_share_a_provider_reference(app_engine: AsyncEngine) -> None:
    provider_ref = f"arg_bonds/{uuid.uuid4().hex}"
    await _insert_asset(app_engine, provider_ref=provider_ref)

    with pytest.raises(IntegrityError, match="assets_provider_provider_ref_key"):
        await _insert_asset(app_engine, provider_ref=provider_ref)


@pytest.mark.parametrize(("column", "value"), [("type", "FOREX"), ("quote_currency", "EUR")])
async def test_an_asset_rejects_values_outside_its_enums(
    app_engine: AsyncEngine, column: str, value: str
) -> None:
    with pytest.raises(DBAPIError, match="invalid input value for enum"):
        await _insert_asset(app_engine, **{column: value})


async def test_the_app_upserts_the_latest_price_of_an_asset(app_engine: AsyncEngine) -> None:
    asset_id = await _insert_asset(app_engine)
    upsert = text(
        "INSERT INTO app.latest_prices (asset_id, price, ts, source)"
        " VALUES (:asset_id, :price, now(), 'data912')"
        " ON CONFLICT (asset_id) DO UPDATE SET price = excluded.price, ts = excluded.ts"
    )

    async with app_engine.begin() as connection:
        await connection.execute(upsert, {"asset_id": asset_id, "price": Decimal("5805")})
        await connection.execute(upsert, {"asset_id": asset_id, "price": Decimal("5810.5")})
    async with app_engine.connect() as connection:
        prices = (
            await connection.scalars(
                text("SELECT price FROM app.latest_prices WHERE asset_id = :id"),
                {"id": asset_id},
            )
        ).all()

    assert prices == [Decimal("5810.5")]


async def test_the_app_deletes_hour_buckets_older_than_retention(app_engine: AsyncEngine) -> None:
    asset_id = await _insert_asset(app_engine)
    old_bucket = datetime(2026, 1, 1, 10, tzinfo=UTC)
    recent_bucket = old_bucket + timedelta(days=120)

    async with app_engine.begin() as connection:
        for bucket in (old_bucket, recent_bucket):
            await connection.execute(
                text(
                    "INSERT INTO app.asset_prices (asset_id, bucket, price, source)"
                    " VALUES (:asset_id, :bucket, 1, 'data912')"
                ),
                {"asset_id": asset_id, "bucket": bucket},
            )
        await connection.execute(
            text("DELETE FROM app.asset_prices WHERE asset_id = :id AND bucket < :cutoff"),
            {"id": asset_id, "cutoff": old_bucket + timedelta(days=1)},
        )
        remaining = (
            await connection.scalars(
                text("SELECT bucket FROM app.asset_prices WHERE asset_id = :id"),
                {"id": asset_id},
            )
        ).all()

    assert remaining == [recent_bucket]


async def test_an_hour_bucket_must_start_on_the_hour(app_engine: AsyncEngine) -> None:
    asset_id = await _insert_asset(app_engine)

    with pytest.raises(IntegrityError, match="asset_prices_bucket_on_the_hour"):
        async with app_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO app.asset_prices (asset_id, bucket, price, source)"
                    " VALUES (:asset_id, '2026-10-19 14:30:00+00', 1, 'data912')"
                ),
                {"asset_id": asset_id},
            )


async def test_fx_mid_is_computed_from_buy_and_sell(app_engine: AsyncEngine) -> None:
    ts = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(microseconds=uuid.uuid4().int % 10**15)

    async with app_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO app.fx_rates (rate_type, ts, buy, sell)"
                " VALUES ('MEP', :ts, 1539.4, 1540.2)"
            ),
            {"ts": ts},
        )
        mid = await connection.scalar(
            text("SELECT mid FROM app.fx_rates WHERE rate_type = 'MEP' AND ts = :ts"), {"ts": ts}
        )

    assert mid == Decimal("1539.800000")


async def test_a_job_run_starts_with_empty_counters_and_rejects_unknown_statuses(
    app_engine: AsyncEngine,
) -> None:
    async with app_engine.begin() as connection:
        row = (
            await connection.execute(
                text(
                    "INSERT INTO app.job_runs (job, started_at, status)"
                    " VALUES ('tick', now(), 'OK') RETURNING items_ok, items_failed, meta"
                )
            )
        ).one()

    assert (row.items_ok, row.items_failed, row.meta) == (0, 0, {})
    with pytest.raises(DBAPIError, match="invalid input value for enum"):
        async with app_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO app.job_runs (job, started_at, status)"
                    " VALUES ('tick', now(), 'RUNNING')"
                )
            )
