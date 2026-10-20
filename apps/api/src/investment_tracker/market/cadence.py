import enum
from collections.abc import Container, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from investment_tracker.market.calendar import MarketHours, is_market_open

# The cron fires every minute with jitter, so a one-minute cadence must not miss a tick
# that lands a few seconds early.
TICK_SLACK = timedelta(seconds=15)


class Fetcher(enum.StrEnum):
    CRYPTO_LIVE = "crypto_live"
    AR_LIVE = "ar_live"
    MEP = "mep"


@dataclass(frozen=True)
class Cadence:
    every: timedelta
    market_hours_only: bool


CADENCES: Mapping[Fetcher, Cadence] = {
    Fetcher.CRYPTO_LIVE: Cadence(every=timedelta(minutes=1), market_hours_only=False),
    Fetcher.AR_LIVE: Cadence(every=timedelta(minutes=1), market_hours_only=True),
    Fetcher.MEP: Cadence(every=timedelta(minutes=5), market_hours_only=True),
}


def is_due(
    cadence: Cadence, now: datetime, last_success: datetime | None, *, is_open: bool
) -> bool:
    if cadence.market_hours_only and not is_open:
        return False
    if last_success is None or last_success > now:
        return True
    return now - last_success >= cadence.every - TICK_SLACK


def due_fetchers(
    now: datetime,
    last_success: Mapping[Fetcher, datetime],
    holidays: Container[date],
    hours: MarketHours,
) -> list[Fetcher]:
    is_open = is_market_open(now, holidays, hours)
    return [
        fetcher
        for fetcher, cadence in CADENCES.items()
        if is_due(cadence, now, last_success.get(fetcher), is_open=is_open)
    ]
