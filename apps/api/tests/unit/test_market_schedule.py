from datetime import UTC, date, datetime, time, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from investment_tracker.market.cadence import CADENCES, Cadence, Fetcher, due_fetchers, is_due
from investment_tracker.market.calendar import ART, MarketHours, is_business_day, is_market_open

HOURS = MarketHours(open=time(11), close=time(17))
MONDAY = date(2026, 10, 19)
NOON_ART = datetime(2026, 10, 19, 15, tzinfo=UTC)
LIVE = Cadence(every=timedelta(minutes=1), market_hours_only=True)

instants = st.integers(min_value=0, max_value=15 * 365 * 86_400).map(
    lambda seconds: datetime(2020, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
)


@given(st.dates())
def test_weekends_are_never_business_days(day: date) -> None:
    assert is_business_day(day, frozenset()) is (day.weekday() < 5)


def test_a_holiday_is_not_a_business_day() -> None:
    assert not is_business_day(MONDAY, frozenset({MONDAY}))


@pytest.mark.parametrize(
    ("utc_time", "is_open"),
    [(time(13, 59), False), (time(14), True), (time(19, 59), True), (time(20), False)],
)
def test_the_market_is_open_from_open_until_close_in_art(utc_time: time, is_open: bool) -> None:
    now = datetime.combine(MONDAY, utc_time, tzinfo=UTC)

    assert is_market_open(now, frozenset(), HOURS) is is_open


def test_the_market_is_closed_on_a_holiday() -> None:
    assert not is_market_open(NOON_ART, frozenset({MONDAY}), HOURS)


def test_the_art_date_decides_the_business_day_near_utc_midnight() -> None:
    friday_night_art = datetime(2026, 10, 24, 1, 30, tzinfo=UTC)
    monday_early_art = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)

    assert is_market_open(friday_night_art, frozenset(), MarketHours(time(22), time(23)))
    assert is_market_open(monday_early_art, frozenset(), MarketHours(time(0), time(1)))
    assert not is_market_open(
        monday_early_art, frozenset({date(2026, 10, 19)}), MarketHours(time(0), time(1))
    )


def test_a_naive_instant_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        is_market_open(NOON_ART.replace(tzinfo=None), frozenset(), HOURS)


def test_market_hours_must_open_before_they_close() -> None:
    with pytest.raises(ValueError, match="open"):
        MarketHours(open=time(17), close=time(11))


def test_a_fetcher_that_never_succeeded_is_due() -> None:
    assert is_due(LIVE, NOON_ART, None, is_open=True)


def test_a_tick_slightly_early_still_runs_a_one_minute_fetcher() -> None:
    last = NOON_ART - timedelta(seconds=58)

    assert is_due(LIVE, NOON_ART, last, is_open=True)


@pytest.mark.parametrize(
    ("fetcher", "boundary"),
    [(Fetcher.AR_LIVE, timedelta(seconds=45)), (Fetcher.MEP, timedelta(minutes=4, seconds=45))],
)
def test_a_fetcher_becomes_due_exactly_at_its_cadence_minus_the_slack(
    fetcher: Fetcher, boundary: timedelta
) -> None:
    cadence = CADENCES[fetcher]

    assert is_due(cadence, NOON_ART, NOON_ART - boundary, is_open=True)
    assert not is_due(
        cadence, NOON_ART, NOON_ART - boundary + timedelta(microseconds=1), is_open=True
    )


def test_only_crypto_is_due_on_a_weekday_holiday_in_market_hours() -> None:
    assert due_fetchers(NOON_ART, {}, frozenset({MONDAY}), HOURS) == [Fetcher.CRYPTO_LIVE]


def test_a_fetcher_is_not_due_well_before_its_cadence() -> None:
    mep = CADENCES[Fetcher.MEP]

    assert not is_due(mep, NOON_ART, NOON_ART - timedelta(minutes=3), is_open=True)


def test_a_last_success_in_the_future_does_not_stall_the_fetcher() -> None:
    assert is_due(LIVE, NOON_ART, NOON_ART + timedelta(hours=1), is_open=True)


@given(now=instants, elapsed=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=3)))
def test_market_hours_fetchers_never_run_while_the_market_is_closed(
    now: datetime, elapsed: timedelta
) -> None:
    assert not is_due(LIVE, now, now - elapsed, is_open=False)


@given(
    now=instants,
    elapsed=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=3)),
    wait=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=3)),
)
def test_once_due_a_fetcher_stays_due_until_it_runs(
    now: datetime, elapsed: timedelta, wait: timedelta
) -> None:
    last = now - elapsed
    if is_due(LIVE, now, last, is_open=True):
        assert is_due(LIVE, now + wait, last, is_open=True)


def test_only_crypto_is_due_while_the_market_is_closed() -> None:
    sunday = datetime(2026, 10, 18, 15, tzinfo=UTC)

    assert due_fetchers(sunday, {}, frozenset(), HOURS) == [Fetcher.CRYPTO_LIVE]


def test_due_fetchers_follow_each_cadence_during_market_hours() -> None:
    last = {
        Fetcher.CRYPTO_LIVE: NOON_ART - timedelta(minutes=1),
        Fetcher.AR_LIVE: NOON_ART - timedelta(seconds=20),
        Fetcher.MEP: NOON_ART - timedelta(minutes=5),
    }

    assert due_fetchers(NOON_ART, last, frozenset(), HOURS) == [Fetcher.CRYPTO_LIVE, Fetcher.MEP]


@pytest.mark.parametrize(
    ("art_time", "is_open"),
    [(time(10, 29), False), (time(10, 30), True), (time(17, 59), True), (time(18), False)],
)
def test_the_default_market_hours_follow_the_byma_equity_session(
    art_time: time, is_open: bool
) -> None:
    now = datetime.combine(MONDAY, art_time, tzinfo=ART)

    assert is_market_open(now, frozenset(), MarketHours()) is is_open
