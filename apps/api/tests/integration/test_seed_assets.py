import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from investment_tracker.core.db import create_sessionmaker
from investment_tracker.market.catalog import load_catalog
from investment_tracker.market.seed import seed_assets

pytestmark = pytest.mark.integration


@pytest.fixture
async def app_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    db_engine = create_async_engine(migrated_database_url)
    yield db_engine
    await db_engine.dispose()


@pytest.fixture
def sessionmaker(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(app_engine)


def _catalog(provider_ref: str, name: str) -> str:
    return f"""
[[assets]]
type = "STOCK_AR"
symbol = "GGAL"
name = "{name}"
quote_currency = "ARS"
provider = "data912"
provider_ref = "{provider_ref}"
"""


async def _rows(engine: AsyncEngine, provider_ref: str) -> list[tuple[str, bool]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT name, is_tracked FROM app.assets WHERE provider_ref = :ref"),
            {"ref": provider_ref},
        )
        return [tuple(row) for row in rows]


async def test_seeding_twice_inserts_each_asset_once_and_tracks_it(
    sessionmaker: async_sessionmaker[AsyncSession], app_engine: AsyncEngine
) -> None:
    provider_ref = f"arg_stocks/{uuid.uuid4().hex}"
    catalog = load_catalog(_catalog(provider_ref, "Galicia"))

    first = await seed_assets(sessionmaker, catalog)
    second = await seed_assets(sessionmaker, catalog)

    assert (first.inserted, first.updated) == (1, 0)
    assert (second.inserted, second.updated) == (0, 1)
    assert await _rows(app_engine, provider_ref) == [("Galicia", True)]


async def test_reseeding_updates_catalog_fields_but_keeps_the_tracking_choice(
    sessionmaker: async_sessionmaker[AsyncSession], app_engine: AsyncEngine, engine: AsyncEngine
) -> None:
    provider_ref = f"arg_stocks/{uuid.uuid4().hex}"
    await seed_assets(sessionmaker, load_catalog(_catalog(provider_ref, "Galicia")))
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE app.assets SET is_tracked = false WHERE provider_ref = :ref"),
            {"ref": provider_ref},
        )

    await seed_assets(sessionmaker, load_catalog(_catalog(provider_ref, "Grupo Galicia")))

    assert await _rows(app_engine, provider_ref) == [("Grupo Galicia", False)]
