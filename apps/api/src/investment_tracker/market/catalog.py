import tomllib
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from investment_tracker.auth.models import Currency
from investment_tracker.market.models import AssetType


class CatalogError(ValueError):
    pass


class SeedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: AssetType
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    quote_currency: Currency
    price_factor: Decimal = Field(default=Decimal(1), gt=0)
    maturity_date: date | None = None
    fci_category: str | None = None
    provider: str = Field(min_length=1, max_length=32)
    provider_ref: str = Field(min_length=1, max_length=200)
    live_provider: str | None = None


class _Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[SeedAsset]


def load_catalog(content: str) -> list[SeedAsset]:
    try:
        raw = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(f"The asset catalog is not valid TOML: {exc}") from None
    try:
        assets = _Catalog.model_validate(raw).assets
    except ValidationError as exc:
        raise CatalogError(f"The asset catalog has invalid entries:\n{exc}") from None
    seen: set[tuple[str, str]] = set()
    for asset in assets:
        key = (asset.provider, asset.provider_ref)
        if key in seen:
            raise CatalogError(
                f"The asset catalog lists {asset.provider} {asset.provider_ref} more than once;"
                " keep one entry per provider reference."
            )
        seen.add(key)
    return assets
