from dataclasses import dataclass

import httpx

from investment_tracker.market.providers.argentinadatos import (
    ArgentinaDatosFci,
    ArgentinaDatosHolidays,
    ArgentinaDatosMepHistory,
)
from investment_tracker.market.providers.base import FxRateProvider
from investment_tracker.market.providers.data912 import Data912Mep
from investment_tracker.market.providers.dolarapi import DolarApiMep

PROVIDER_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@dataclass(frozen=True)
class ProviderRegistry:
    mep: FxRateProvider
    mep_fallback: FxRateProvider
    mep_history: ArgentinaDatosMepHistory
    holidays: ArgentinaDatosHolidays
    fci: ArgentinaDatosFci


def create_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=PROVIDER_TIMEOUT, headers={"User-Agent": "investment-tracker"})


def build_registry(client: httpx.AsyncClient) -> ProviderRegistry:
    return ProviderRegistry(
        mep=DolarApiMep(client),
        mep_fallback=Data912Mep(client),
        mep_history=ArgentinaDatosMepHistory(client),
        holidays=ArgentinaDatosHolidays(client),
        fci=ArgentinaDatosFci(client),
    )
