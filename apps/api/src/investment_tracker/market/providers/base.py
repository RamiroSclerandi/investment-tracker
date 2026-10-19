import asyncio
import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Protocol

import httpx
from pydantic import Field, StringConstraints, TypeAdapter, ValidationError

from investment_tracker.auth.models import Currency

ART = timezone(timedelta(hours=-3), "ART")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 10_000
MAX_DETAIL_LENGTH = 200
REQUEST_DEADLINE_SECONDS = 20.0

Amount = Annotated[Decimal, Field(gt=0, lt=Decimal("1E20"), max_digits=30, allow_inf_nan=False)]
FxAmount = Annotated[Decimal, Field(gt=0, lt=Decimal("1E14"), max_digits=20, allow_inf_nan=False)]
Text = Annotated[str, StringConstraints(max_length=200, pattern=r"^[^\x00-\x1f\x7f-\x9f]*$")]
type Items[T] = Annotated[list[T], Field(max_length=MAX_ITEMS)]

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
        super().__init__(f"{provider}: {detail[:MAX_DETAIL_LENGTH]}")
        self.provider = provider


def check_spread(buy: Decimal, sell: Decimal) -> None:
    if sell < buy:
        raise ValueError("sell is below buy")


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
        # The httpx timeout is per read, so a trickling server needs an overall deadline.
        async with asyncio.timeout(REQUEST_DEADLINE_SECONDS):
            async with client.stream("GET", url) as response:
                if response.status_code != httpx.codes.OK:
                    raise ProviderError(provider, f"{url} answered HTTP {response.status_code}")
                body = await _read_capped(response, provider, url)
    except TimeoutError as exc:
        raise ProviderError(provider, f"{url} missed the request deadline") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(provider, f"request to {url} failed: {type(exc).__name__}") from exc
    try:
        return shape.validate_json(body)
    except ValidationError as exc:
        raise ProviderError(provider, f"{url} returned an unexpected payload") from exc


async def _read_capped(response: httpx.Response, provider: str, url: str) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ProviderError(provider, f"{url} response exceeds {MAX_RESPONSE_BYTES} bytes")
    return bytes(body)
