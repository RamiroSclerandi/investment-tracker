from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, literal_column
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from investment_tracker.market.catalog import SeedAsset
from investment_tracker.market.models import Asset

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
