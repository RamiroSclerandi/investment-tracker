from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Self

import httpx
from pydantic import BaseModel, TypeAdapter, model_validator

from investment_tracker.auth.models import Currency
from investment_tracker.market.providers.base import (
    Amount,
    Clock,
    DailyFxRate,
    FxAmount,
    Holiday,
    HolidayKind,
    Items,
    PricePoint,
    ProviderError,
    Text,
    art_midnight,
    check_spread,
    get_json,
    utc_now,
)

BASE_URL = "https://api.argentinadatos.com/v1"
NAME = "argentinadatos"
FCI_CATEGORIES = frozenset({"mercadoDinero", "rentaVariable", "rentaFija", "rentaMixta"})
SATURDAY = 5


class _Holiday(BaseModel):
    fecha: date
    tipo: HolidayKind
    nombre: Text


class _DailyRate(BaseModel):
    fecha: date
    compra: FxAmount
    venta: FxAmount

    @model_validator(mode="after")
    def sell_not_below_buy(self) -> Self:
        check_spread(self.compra, self.venta)
        return self


class _Fund(BaseModel):
    fondo: Text
    fecha: date
    vcp: Amount


_HOLIDAYS = TypeAdapter(Items[_Holiday])
_DAILY_RATES = TypeAdapter(Items[_DailyRate])
_FUNDS = TypeAdapter(Items[_Fund])


class ArgentinaDatosHolidays:
    name = NAME

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def holidays(self, year: int) -> list[Holiday]:
        rows = await get_json(self._client, NAME, f"{BASE_URL}/feriados/{year}", _HOLIDAYS)
        return [Holiday(day=r.fecha, kind=r.tipo, name=r.nombre) for r in rows]


class ArgentinaDatosMepHistory:
    name = NAME

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def history(self, start: date, end: date) -> list[DailyFxRate]:
        url = f"{BASE_URL}/cotizaciones/dolares/bolsa"
        rows = await get_json(self._client, NAME, url, _DAILY_RATES)
        return [
            DailyFxRate(day=r.fecha, buy=r.compra, sell=r.venta)
            for r in rows
            if start <= r.fecha <= end and r.fecha.weekday() < SATURDAY
        ]


class ArgentinaDatosFci:
    name = NAME

    def __init__(self, client: httpx.AsyncClient, now: Clock = utc_now) -> None:
        self._client = client
        self._now = now

    async def latest(self, refs: Sequence[str]) -> dict[str, PricePoint]:
        by_category: dict[str, set[str]] = defaultdict(set)
        for ref in refs:
            category, _, fund = ref.partition("/")
            if category not in FCI_CATEGORIES:
                raise ProviderError(NAME, f"unknown FCI category {category[:40]!r}")
            by_category[category].add(fund)
        points: dict[str, PricePoint] = {}
        for category, funds in by_category.items():
            url = f"{BASE_URL}/finanzas/fci/{category}/ultimo"
            rows = await get_json(self._client, NAME, url, _FUNDS)
            name_counts = Counter(r.fondo for r in rows)
            fetched_at = self._now()
            for row in rows:
                if row.fondo in funds and name_counts[row.fondo] == 1:
                    points[f"{category}/{row.fondo}"] = PricePoint(
                        symbol=row.fondo,
                        price=row.vcp,
                        currency=Currency.ARS,
                        fetched_at=fetched_at,
                        source_ts=art_midnight(row.fecha),
                    )
        return points

    async def history(self, ref: str, start: date, end: date) -> list[PricePoint]:
        return []
