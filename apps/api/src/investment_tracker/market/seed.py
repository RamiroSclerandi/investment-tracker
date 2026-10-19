from collections.abc import Sequence
from itertools import batched

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_tracker.market.catalog import SeedAsset
from investment_tracker.market.repository import AssetRepository, UpsertCounts

BATCH_SIZE = 200


async def seed_assets(
    sessionmaker: async_sessionmaker[AsyncSession], assets: Sequence[SeedAsset]
) -> UpsertCounts:
    inserted = updated = 0
    async with sessionmaker() as session, session.begin():
        repository = AssetRepository(session)
        for batch in batched(assets, BATCH_SIZE, strict=False):
            counts = await repository.upsert_catalog(batch)
            inserted += counts.inserted
            updated += counts.updated
    return UpsertCounts(inserted, updated)
