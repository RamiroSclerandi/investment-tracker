from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Self

import httpx
from pydantic import BaseModel, TypeAdapter, model_validator

from investment_tracker.auth.models import Currency
from investment_tracker.market.providers.base import (
    RAW_ROWS,
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
    require_valid_rows,
    utc_now,
    valid_or_none,
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
_DAILY_RATE = TypeAdapter(_DailyRate)
_FUND = TypeAdapter(_Fund)


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
        rows = await get_json(self._client, NAME, url, RAW_ROWS)
        rates = [r for r in (valid_or_none(_DAILY_RATE, raw) for raw in rows) if r is not None]
        require_valid_rows(NAME, url, len(rows), len(rates))
        return [
            DailyFxRate(day=r.fecha, buy=r.compra, sell=r.venta)
            for r in rates
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
            rows = await get_json(self._client, NAME, url, RAW_ROWS)
            named = [raw for raw in rows if isinstance(raw.get("fondo"), str)]
            name_counts = Counter(raw["fondo"] for raw in named)
            candidates = [r for r in named if r["fondo"] in funds and name_counts[r["fondo"]] == 1]
            fetched_at = self._now()
            valid = [f for f in (valid_or_none(_FUND, raw) for raw in candidates) if f is not None]
            require_valid_rows(NAME, url, len(candidates), len(valid))
            for row in valid:
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
