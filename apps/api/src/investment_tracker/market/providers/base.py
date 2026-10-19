import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

import httpx
from pydantic import TypeAdapter, ValidationError

from investment_tracker.auth.models import Currency

ART = timezone(timedelta(hours=-3), "ART")

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def art_midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=ART).astimezone(UTC)


class Settlement(enum.StrEnum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"


class HolidayKind(enum.StrEnum):
    INAMOVIBLE = "inamovible"
    TRASLADABLE = "trasladable"
    PUENTE = "puente"


@dataclass(frozen=True)
class PricePoint:
    symbol: str
    price: Decimal
    currency: Currency
    fetched_at: datetime
    source_ts: datetime | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    settlement: Settlement | None = None
    price_basis: int = 1


@dataclass(frozen=True)
class FxQuote:
    buy: Decimal
    sell: Decimal
    source_ts: datetime | None
    fetched_at: datetime


@dataclass(frozen=True)
class DailyFxRate:
    day: date
    buy: Decimal
    sell: Decimal


@dataclass(frozen=True)
class Holiday:
    day: date
    kind: HolidayKind
    name: str


class ProviderError(Exception):
    def __init__(self, provider: str, detail: str) -> None:
        super().__init__(f"{provider}: {detail}")
        self.provider = provider


class PriceProvider(Protocol):
    name: str

    async def latest(self, refs: Sequence[str]) -> dict[str, PricePoint]: ...

    async def history(self, ref: str, start: date, end: date) -> list[PricePoint]: ...


class FxRateProvider(Protocol):
    name: str

    async def latest(self) -> FxQuote: ...


async def get_json[T](
    client: httpx.AsyncClient, provider: str, url: str, shape: TypeAdapter[T]
) -> T:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        raise ProviderError(provider, f"request to {url} failed: {type(exc).__name__}") from exc
    if response.status_code != httpx.codes.OK:
        raise ProviderError(provider, f"{url} answered HTTP {response.status_code}")
    try:
        payload: Any = response.json()
        return shape.validate_python(payload)
    except (ValueError, ValidationError) as exc:
        raise ProviderError(provider, f"{url} returned an unexpected payload") from exc
