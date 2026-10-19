from datetime import datetime
from typing import Self

import httpx
from pydantic import AwareDatetime, BaseModel, TypeAdapter, model_validator

from investment_tracker.market.providers.base import (
    Clock,
    FxAmount,
    FxQuote,
    check_spread,
    get_json,
    utc_now,
)

BASE_URL = "https://dolarapi.com"


class _Quote(BaseModel):
    compra: FxAmount
    venta: FxAmount
    fechaActualizacion: AwareDatetime  # noqa: N815

    @model_validator(mode="after")
    def sell_not_below_buy(self) -> Self:
        check_spread(self.compra, self.venta)
        return self


_QUOTE = TypeAdapter(_Quote)


class DolarApiMep:
    name = "dolarapi"

    def __init__(self, client: httpx.AsyncClient, now: Clock = utc_now) -> None:
        self._client = client
        self._now = now

    async def latest(self) -> FxQuote:
        quote = await get_json(self._client, self.name, f"{BASE_URL}/v1/dolares/bolsa", _QUOTE)
        source_ts: datetime = quote.fechaActualizacion
        return FxQuote(
            buy=quote.compra, sell=quote.venta, source_ts=source_ts, fetched_at=self._now()
        )
