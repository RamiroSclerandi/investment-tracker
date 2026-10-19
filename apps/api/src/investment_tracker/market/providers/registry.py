from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from investment_tracker.market.providers.argentinadatos import (
    ArgentinaDatosFci,
    ArgentinaDatosHolidays,
    ArgentinaDatosMepHistory,
)
from investment_tracker.market.providers.base import FxRateProvider, PriceProvider
from investment_tracker.market.providers.coingecko import CoinGeckoHistory
from investment_tracker.market.providers.data912 import Data912Mep, Data912Prices
from investment_tracker.market.providers.dolarapi import DolarApiMep
from investment_tracker.market.providers.kraken import KrakenTicker

PROVIDER_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
PROVIDER_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)


@dataclass(frozen=True)
class ProviderRegistry:
    mep: FxRateProvider
    mep_fallback: FxRateProvider
    mep_history: ArgentinaDatosMepHistory
    holidays: ArgentinaDatosHolidays
    fci: ArgentinaDatosFci
    crypto_live: PriceProvider
    crypto_history: PriceProvider
    prices: PriceProvider


def create_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=PROVIDER_TIMEOUT,
        limits=PROVIDER_LIMITS,
        follow_redirects=False,
        headers={"User-Agent": "investment-tracker", "Accept-Encoding": "identity"},
    )


def build_registry(
    client: httpx.AsyncClient, coingecko_api_key: SecretStr | None = None
) -> ProviderRegistry:
    api_key = coingecko_api_key.get_secret_value() if coingecko_api_key else None
    return ProviderRegistry(
        mep=DolarApiMep(client),
        mep_fallback=Data912Mep(client),
        mep_history=ArgentinaDatosMepHistory(client),
        holidays=ArgentinaDatosHolidays(client),
        fci=ArgentinaDatosFci(client),
        crypto_live=KrakenTicker(client),
        crypto_history=CoinGeckoHistory(client, api_key=api_key),
        prices=Data912Prices(client),
    )
