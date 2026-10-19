from decimal import Decimal
from pathlib import Path

import pytest

from investment_tracker.auth.models import Currency
from investment_tracker.market.catalog import CatalogError, load_catalog
from investment_tracker.market.models import AssetType

SEED_FILE = Path(__file__).resolve().parents[2] / "seed" / "assets.toml"

AL30 = """
[[assets]]
type = "SOV_BONDS"
symbol = "AL30"
name = "Bonar 2030 USD"
quote_currency = "ARS"
price_factor = "0.01"
provider = "data912"
provider_ref = "arg_bonds/AL30"
"""
BTC = """
[[assets]]
type = "CRYPTO"
symbol = "BTC"
name = "Bitcoin"
quote_currency = "USD"
provider = "coingecko"
provider_ref = "bitcoin"
live_provider = "kraken"
"""


def test_load_catalog_parses_each_asset_with_a_unit_factor_by_default() -> None:
    assets = load_catalog(AL30 + BTC)

    assert [(a.type, a.symbol, a.price_factor) for a in assets] == [
        (AssetType.SOV_BONDS, "AL30", Decimal("0.01")),
        (AssetType.CRYPTO, "BTC", Decimal(1)),
    ]
    assert assets[1].quote_currency is Currency.USD
    assert assets[1].live_provider == "kraken"
    assert assets[0].live_provider is None


def test_load_catalog_rejects_an_unknown_asset_type() -> None:
    with pytest.raises(CatalogError, match=r"assets\.0\.type"):
        load_catalog(AL30.replace("SOV_BONDS", "FOREX"))


def test_load_catalog_rejects_a_non_positive_price_factor() -> None:
    with pytest.raises(CatalogError, match="price_factor"):
        load_catalog(AL30.replace('"0.01"', '"0"'))


def test_load_catalog_rejects_two_assets_with_the_same_provider_reference() -> None:
    with pytest.raises(CatalogError, match="data912 arg_bonds/AL30"):
        load_catalog(AL30 + AL30)


def test_load_catalog_rejects_malformed_toml() -> None:
    with pytest.raises(CatalogError, match="TOML"):
        load_catalog("[[assets]\n")


def test_the_committed_seed_file_is_a_valid_catalog() -> None:
    assets = load_catalog(SEED_FILE.read_text(encoding="utf-8"))

    assert len(assets) > 0
    assert {a.type for a in assets} >= {AssetType.CRYPTO, AssetType.SOV_BONDS, AssetType.CEDEAR}
