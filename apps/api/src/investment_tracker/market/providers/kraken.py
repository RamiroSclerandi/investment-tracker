from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, TypeAdapter

from investment_tracker.auth.models import Currency
from investment_tracker.market.providers.base import (
    Amount,
    Clock,
    Items,
    PricePoint,
    ProviderError,
    Quote,
    Text,
    get_json,
    require_valid_rows,
    utc_now,
    valid_or_none,
)

BASE_URL = "https://api.kraken.com/0/public"
NAME = "kraken"
USD_QUOTES = frozenset({"USD", "ZUSD"})
SYMBOL_ALIASES = {"XBT": "BTC", "XDG": "DOGE"}
PAIRS_TTL = timedelta(hours=1)
UNKNOWN_PAIR = "EQuery:Unknown asset pair"


class _UnknownPairError(ProviderError):
    pass


class _Pair(BaseModel):
    altname: Text
    wsname: Text
    quote: Text
    status: Text


class _Envelope(BaseModel):
    error: Items[Text]
    result: dict[Text, dict[str, Any]]


class _TickerRow(BaseModel):
    a: tuple[Quote, Decimal, Decimal]
    b: tuple[Quote, Decimal, Decimal]
    c: tuple[Amount, Decimal]


_ENVELOPE = TypeAdapter(_Envelope)
_PAIR = TypeAdapter(_Pair)
_TICKER_ROW = TypeAdapter(_TickerRow)


@dataclass(frozen=True)
class _UsdPair:
    key: str
    altname: str


class KrakenTicker:
    name = NAME

    def __init__(self, client: httpx.AsyncClient, now: Clock = utc_now) -> None:
        self._client = client
        self._now = now
        self._pairs: dict[str, _UsdPair] | None = None
        self._pairs_loaded_at = datetime.min.replace(tzinfo=UTC)

    async def latest(self, refs: Sequence[str]) -> dict[str, PricePoint]:
        try:
            return await self._quote(refs)
        except _UnknownPairError:
            self._pairs = None
            return await self._quote(refs)

    async def _quote(self, refs: Sequence[str]) -> dict[str, PricePoint]:
        pairs = await self._usd_pairs()
        wanted = {pairs[ref].key: ref for ref in refs if ref in pairs}
        if not wanted:
            return {}
        altnames = ",".join(pairs[ref].altname for ref in wanted.values())
        url = f"{BASE_URL}/Ticker"
        ticker = await self._get(url, {"pair": altnames})
        fetched_at = self._now()
        points: dict[str, PricePoint] = {}
        for key, symbol in wanted.items():
            row = valid_or_none(_TICKER_ROW, ticker.result.get(key))
            if row is not None:
                points[symbol] = PricePoint(
                    symbol=symbol,
                    price=row.c[0],
                    currency=Currency.USD,
                    fetched_at=fetched_at,
                    bid=row.b[0] or None,
                    ask=row.a[0] or None,
                )
        require_valid_rows(NAME, url, len(wanted), len(points))
        return points

    async def history(self, ref: str, start: date, end: date) -> list[PricePoint]:
        raise ProviderError(NAME, "Kraken serves live quotes only; history comes from CoinGecko")

    async def _usd_pairs(self) -> dict[str, _UsdPair]:
        now = self._now()
        if self._pairs is None or now - self._pairs_loaded_at >= PAIRS_TTL:
            listing = await self._get(f"{BASE_URL}/AssetPairs", None)
            self._pairs_loaded_at = now
            self._pairs = {}
            for key, raw in listing.result.items():
                pair = valid_or_none(_PAIR, raw)
                if pair is None or pair.quote not in USD_QUOTES or pair.status != "online":
                    continue
                base = pair.wsname.partition("/")[0]
                self._pairs.setdefault(SYMBOL_ALIASES.get(base, base), _UsdPair(key, pair.altname))
        return self._pairs

    async def _get(self, url: str, params: dict[str, str] | None) -> _Envelope:
        payload = await get_json(self._client, NAME, url, _ENVELOPE, params=params)
        if UNKNOWN_PAIR in payload.error:
            raise _UnknownPairError(NAME, f"{url} returned errors: {', '.join(payload.error)}")
        if payload.error:
            raise ProviderError(NAME, f"{url} returned errors: {', '.join(payload.error)}")
        return payload
