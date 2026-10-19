from decimal import Decimal

import httpx
from pydantic import BaseModel, TypeAdapter

from investment_tracker.market.providers.base import (
    Clock,
    FxQuote,
    ProviderError,
    get_json,
    utc_now,
)

BASE_URL = "https://data912.com"
MEP_REFERENCE_TICKER = "AL30"


class _MepRow(BaseModel):
    ticker: str
    bid: Decimal
    ask: Decimal


_MEP_ROWS = TypeAdapter(list[_MepRow])


class Data912Mep:
    name = "data912"

    def __init__(self, client: httpx.AsyncClient, now: Clock = utc_now) -> None:
        self._client = client
        self._now = now

    async def latest(self) -> FxQuote:
        rows = await get_json(self._client, self.name, f"{BASE_URL}/live/mep", _MEP_ROWS)
        row = next((r for r in rows if r.ticker == MEP_REFERENCE_TICKER), None)
        if row is None:
            raise ProviderError(self.name, f"/live/mep has no {MEP_REFERENCE_TICKER} row")
        return FxQuote(buy=row.bid, sell=row.ask, source_ts=None, fetched_at=self._now())
