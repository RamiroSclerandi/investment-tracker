from datetime import datetime
from decimal import Decimal

import httpx
from pydantic import AwareDatetime, BaseModel, TypeAdapter

from investment_tracker.market.providers.base import Clock, FxQuote, get_json, utc_now

BASE_URL = "https://dolarapi.com"


class _Quote(BaseModel):
    compra: Decimal
    venta: Decimal
    fechaActualizacion: AwareDatetime  # noqa: N815


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
