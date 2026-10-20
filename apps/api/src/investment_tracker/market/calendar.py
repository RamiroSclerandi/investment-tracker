from collections.abc import Container
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

# Fixed offset: Argentina has had no DST since 2009 and Windows hosts lack tzdata.
ART = timezone(timedelta(hours=-3), "ART")


@dataclass(frozen=True)
class MarketHours:
    open: time = time(10, 30)
    close: time = time(18)

    def __post_init__(self) -> None:
        if self.open >= self.close:
            raise ValueError("market hours must open before they close")


def is_business_day(day: date, holidays: Container[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def is_market_open(now: datetime, holidays: Container[date], hours: MarketHours) -> bool:
    if now.tzinfo is None:
        raise ValueError("now must carry a timezone")
    local = now.astimezone(ART)
    return is_business_day(local.date(), holidays) and hours.open <= local.time() < hours.close
