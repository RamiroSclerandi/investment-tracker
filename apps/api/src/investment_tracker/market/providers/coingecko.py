import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import httpx
from pydantic import BaseModel, Field, TypeAdapter

from investment_tracker.auth.models import Currency
from investment_tracker.market.providers.base import (
    Amount,
    Clock,
    Items,
    PricePoint,
    ProviderError,
    art_midnight,
    get_json,
    utc_now,
)

BASE_URL = "https://api.coingecko.com/api/v3"
NAME = "coingecko"
DEMO_KEY_HEADER = "x-cg-demo-api-key"
COIN_ID = re.compile(r"[a-z0-9-]{1,64}")
MAX_EPOCH_MILLIS = 4_102_444_800_000


class _Chart(BaseModel):
    prices: Items[tuple[Annotated[int, Field(ge=0, lt=MAX_EPOCH_MILLIS)], Amount]]


_CHART = TypeAdapter(_Chart)


class CoinGeckoHistory:
    name = NAME

    def __init__(
        self, client: httpx.AsyncClient, api_key: str | None = None, now: Clock = utc_now
    ) -> None:
        self._client = client
        self._headers = {DEMO_KEY_HEADER: api_key} if api_key else None
        self._now = now

    async def latest(self, refs: Sequence[str]) -> dict[str, PricePoint]:
        raise ProviderError(NAME, "CoinGecko serves history only; live quotes come from Kraken")

    async def history(self, ref: str, start: date, end: date) -> list[PricePoint]:
        if COIN_ID.fullmatch(ref) is None:
            raise ProviderError(NAME, f"malformed coin id {ref[:40]!r}")
        params = {
            "vs_currency": "usd",
            "from": str(int(art_midnight(start).timestamp())),
            "to": str(int(art_midnight(end + timedelta(days=1)).timestamp())),
        }
        url = f"{BASE_URL}/coins/{ref}/market_chart/range"
        chart = await get_json(
            self._client, NAME, url, _CHART, params=params, headers=self._headers
        )
        fetched_at = self._now()
        return [
            PricePoint(
                symbol=ref,
                price=price,
                currency=Currency.USD,
                fetched_at=fetched_at,
                source_ts=datetime.fromtimestamp(millis / 1000, tz=UTC),
            )
            for millis, price in chart.prices
        ]
