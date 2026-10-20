import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Self

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, model_validator

from investment_tracker.auth.models import Currency
from investment_tracker.market.providers.base import (
    RAW_ROWS,
    Amount,
    Clock,
    FxAmount,
    FxQuote,
    Items,
    PricePoint,
    ProviderError,
    Quote,
    Text,
    art_midnight,
    check_spread,
    get_json,
    require_valid_rows,
    utc_now,
    valid_or_none,
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


LIVE_PANELS = frozenset(
    {"arg_stocks", "arg_cedears", "arg_bonds", "arg_corp", "arg_notes", "usa_stocks", "usa_adrs"}
)
PER_100_PANELS = frozenset({"arg_bonds", "arg_corp", "arg_notes"})
HISTORY_KINDS = {"arg_bonds": "bonds", "arg_stocks": "stocks", "arg_cedears": "cedears"}
DOLLAR_SUFFIXES = ("D", "C")
SYMBOL = re.compile(r"[A-Z0-9]{1,20}")


class _LiveRow(BaseModel):
    symbol: Text
    c: Amount
    px_bid: Quote | None = None
    px_ask: Quote | None = None


class _Bar(BaseModel):
    date: date
    c: Amount


_LIVE_ROW = TypeAdapter(_LiveRow)
_BAR = TypeAdapter(_Bar)


class Data912Prices:
    name = "data912"

    def __init__(self, client: httpx.AsyncClient, now: Clock = utc_now) -> None:
        self._client = client
        self._now = now

    async def latest(self, refs: Sequence[str]) -> dict[str, PricePoint]:
        by_panel: dict[str, set[str]] = defaultdict(set)
        for ref in refs:
            panel, _, symbol = ref.partition("/")
            if panel not in LIVE_PANELS:
                raise ProviderError(self.name, f"unknown data912 panel {panel[:40]!r}")
            by_panel[panel].add(symbol)
        points: dict[str, PricePoint] = {}
        errors: list[ProviderError] = []
        for panel, symbols in by_panel.items():
            try:
                points.update(await self._panel(panel, symbols))
            except ProviderError as exc:
                errors.append(exc)
        if errors and not points:
            raise errors[0]
        return points

    async def _panel(self, panel: str, symbols: set[str]) -> dict[str, PricePoint]:
        url = f"{BASE_URL}/live/{panel}"
        rows = await get_json(self._client, self.name, url, RAW_ROWS)
        candidates = [
            raw for raw in rows if isinstance(sym := raw.get("symbol"), str) and sym in symbols
        ]
        fetched_at = self._now()
        valid = [r for r in (valid_or_none(_LIVE_ROW, raw) for raw in candidates) if r]
        require_valid_rows(self.name, url, len(candidates), len(valid))
        return {
            f"{panel}/{row.symbol}": PricePoint(
                symbol=row.symbol,
                price=row.c,
                currency=_currency(panel, row.symbol),
                fetched_at=fetched_at,
                bid=row.px_bid or None,
                ask=row.px_ask or None,
                price_basis=_price_basis(panel),
            )
            for row in valid
        }

    async def history(self, ref: str, start: date, end: date) -> list[PricePoint]:
        panel, _, symbol = ref.partition("/")
        kind = HISTORY_KINDS.get(panel)
        if kind is None:
            raise ProviderError(self.name, f"no data912 history for panel {panel[:40]!r}")
        if SYMBOL.fullmatch(symbol) is None:
            raise ProviderError(self.name, f"malformed symbol {symbol[:40]!r}")
        url = f"{BASE_URL}/historical/{kind}/{symbol}"
        rows = await get_json(self._client, self.name, url, RAW_ROWS)
        fetched_at = self._now()
        bars = [b for b in (valid_or_none(_BAR, raw) for raw in rows) if b is not None]
        require_valid_rows(self.name, url, len(rows), len(bars))
        return [
            PricePoint(
                symbol=symbol,
                price=bar.c,
                currency=_currency(panel, symbol),
                fetched_at=fetched_at,
                source_ts=art_midnight(bar.date),
                price_basis=_price_basis(panel),
            )
            for bar in bars
            if start <= bar.date <= end
        ]


def _currency(panel: str, symbol: str) -> Currency:
    if panel.startswith("usa_"):
        return Currency.USD
    # On bond and ON panels the D (MEP) and C (cable) suffixes mark the dollar legs; stock
    # tickers such as YPFD use the same letters for share classes.
    if panel in {"arg_bonds", "arg_corp"} and symbol.endswith(DOLLAR_SUFFIXES):
        return Currency.USD
    return Currency.ARS


def _price_basis(panel: str) -> int:
    return 100 if panel in PER_100_PANELS else 1
