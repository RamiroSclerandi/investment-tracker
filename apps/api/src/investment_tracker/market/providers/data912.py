from typing import Self

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, model_validator

from investment_tracker.market.providers.base import (
    Clock,
    FxAmount,
    FxQuote,
    Items,
    ProviderError,
    Text,
    check_spread,
    get_json,
    utc_now,
)

BASE_URL = "https://data912.com"
MEP_REFERENCE_TICKER = "AL30"


class _MepRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    ticker: Text


class _MepQuote(BaseModel):
    bid: FxAmount
    ask: FxAmount

    @model_validator(mode="after")
    def ask_not_below_bid(self) -> Self:
        check_spread(self.bid, self.ask)
        return self


_MEP_ROWS = TypeAdapter(Items[_MepRow])
_MEP_QUOTE = TypeAdapter(_MepQuote)


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
        # Only the reference row is validated strictly: illiquid tickers quote 0 and must not
        # take the whole fallback down.
        try:
            quote = _MEP_QUOTE.validate_python(row.model_extra)
        except ValidationError as exc:
            raise ProviderError(
                self.name, f"/live/mep returned an unexpected payload for {MEP_REFERENCE_TICKER}"
            ) from exc
        return FxQuote(buy=quote.bid, sell=quote.ask, source_ts=None, fetched_at=self._now())
