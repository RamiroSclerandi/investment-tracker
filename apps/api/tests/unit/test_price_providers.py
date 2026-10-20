import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from investment_tracker.auth.models import Currency
from investment_tracker.market.providers.base import ProviderError
from investment_tracker.market.providers.coingecko import CoinGeckoHistory
from investment_tracker.market.providers.data912 import Data912Prices
from investment_tracker.market.providers.kraken import KrakenTicker

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers"
NOW = datetime(2026, 10, 19, 19, 45, tzinfo=UTC)


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client(routes: dict[str, Any], seen: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"error": "Not found"})
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _clock() -> Callable[[], datetime]:
    return lambda: NOW


def _kraken_routes(ticker: Any | None = None) -> dict[str, Any]:
    return {
        "/0/public/AssetPairs": _fixture("kraken_asset_pairs.json"),
        "/0/public/Ticker": ticker if ticker is not None else _fixture("kraken_ticker.json"),
    }


async def test_kraken_maps_each_symbol_to_its_last_trade_bid_and_ask_in_usd() -> None:
    client = _client(_kraken_routes())

    points = await KrakenTicker(client, now=_clock()).latest(["BTC", "DOGE", "ADA"])

    assert set(points) == {"BTC", "DOGE", "ADA"}
    btc = points["BTC"]
    assert (btc.price, btc.bid, btc.ask) == (
        Decimal("81970.70000"),
        Decimal("81970.60000"),
        Decimal("81970.70000"),
    )
    assert (btc.currency, btc.fetched_at, btc.source_ts) == (Currency.USD, NOW, None)
    assert points["DOGE"].price == Decimal("0.079258200")


async def test_kraken_skips_symbols_without_a_usd_pair_and_does_not_request_them() -> None:
    seen: list[httpx.Request] = []
    client = _client(_kraken_routes(), seen)

    points = await KrakenTicker(client, now=_clock()).latest(["BTC", "NOTACOIN"])

    assert list(points) == ["BTC"]
    ticker = next(r for r in seen if r.url.path == "/0/public/Ticker")
    assert ticker.url.params["pair"] == "XBTUSD"


async def test_kraken_reports_ticker_errors_as_a_provider_error() -> None:
    client = _client(_kraken_routes({"error": ["EQuery:Unknown asset pair"], "result": {}}))

    with pytest.raises(ProviderError, match=r"kraken.*error"):
        await KrakenTicker(client, now=_clock()).latest(["BTC"])


async def test_kraken_skips_a_pair_with_an_invalid_price_and_keeps_the_rest() -> None:
    ticker = _fixture("kraken_ticker.json")
    ticker["result"]["XDGUSD"]["c"] = ["0", "1"]
    client = _client(_kraken_routes(ticker))

    points = await KrakenTicker(client, now=_clock()).latest(["BTC", "DOGE"])

    assert list(points) == ["BTC"]


async def test_kraken_loads_the_pair_map_once() -> None:
    seen: list[httpx.Request] = []
    ticker = KrakenTicker(_client(_kraken_routes(), seen), now=_clock())

    await ticker.latest(["BTC"])
    await ticker.latest(["ETH"])

    assert [r.url.path for r in seen].count("/0/public/AssetPairs") == 1


async def test_kraken_reloads_the_pair_map_after_an_hour() -> None:
    seen: list[httpx.Request] = []
    now = [NOW]
    ticker = KrakenTicker(_client(_kraken_routes(), seen), now=lambda: now[0])

    await ticker.latest(["BTC"])
    now[0] = NOW + timedelta(minutes=59)
    await ticker.latest(["BTC"])
    now[0] = NOW + timedelta(hours=1)
    await ticker.latest(["BTC"])

    assert [r.url.path for r in seen].count("/0/public/AssetPairs") == 2


async def test_kraken_reloads_the_pair_map_once_when_a_cached_pair_was_delisted() -> None:
    listings = [_fixture("kraken_asset_pairs.json"), _fixture("kraken_asset_pairs.json")]
    del listings[1]["result"]["XETHZUSD"]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/0/public/AssetPairs":
            return httpx.Response(200, json=listings.pop(0))
        if "ETHUSD" in request.url.params["pair"]:
            return httpx.Response(200, json={"error": ["EQuery:Unknown asset pair"], "result": {}})
        return httpx.Response(200, json=_fixture("kraken_ticker.json"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ticker = KrakenTicker(client, now=_clock())
    await ticker.latest(["BTC"])

    points = await ticker.latest(["BTC", "ETH"])

    assert list(points) == ["BTC"]
    assert [r.url.path for r in seen].count("/0/public/AssetPairs") == 2


async def test_kraken_fails_the_batch_when_the_reloaded_map_still_has_the_rejected_pair() -> None:
    seen: list[httpx.Request] = []
    client = _client(_kraken_routes({"error": ["EQuery:Unknown asset pair"], "result": {}}), seen)

    with pytest.raises(ProviderError, match="Unknown asset pair"):
        await KrakenTicker(client, now=_clock()).latest(["BTC", "ETH"])
    assert [r.url.path for r in seen].count("/0/public/Ticker") == 2


async def test_kraken_has_no_history() -> None:
    with pytest.raises(ProviderError, match="kraken"):
        await KrakenTicker(_client({}), now=_clock()).history("BTC", date(2026, 1, 1), NOW.date())


async def test_coingecko_maps_the_usd_price_series_with_source_timestamps() -> None:
    seen: list[httpx.Request] = []
    route = "/api/v3/coins/bitcoin/market_chart/range"
    client = _client({route: _fixture("coingecko_market_chart_range_bitcoin_30d.json")}, seen)

    points = await CoinGeckoHistory(client, now=_clock()).history(
        "bitcoin", date(2026, 9, 19), date(2026, 10, 19)
    )

    assert len(points) == 24
    first = points[0]
    assert (first.symbol, first.currency, first.fetched_at) == ("bitcoin", Currency.USD, NOW)
    assert first.price == Decimal("81226.58014364234")
    assert first.source_ts == datetime.fromtimestamp(1789858800, tz=UTC)
    assert dict(seen[0].url.params) == {
        "vs_currency": "usd",
        "from": str(int(datetime(2026, 9, 19, 3, tzinfo=UTC).timestamp())),
        "to": str(int(datetime(2026, 10, 20, 3, tzinfo=UTC).timestamp())),
    }


@pytest.mark.parametrize(("api_key", "expected"), [("demo-key", "demo-key"), (None, None)])
async def test_coingecko_sends_the_demo_key_header_only_when_configured(
    api_key: str | None, expected: str | None
) -> None:
    seen: list[httpx.Request] = []
    route = "/api/v3/coins/bitcoin/market_chart/range"
    client = _client({route: _fixture("coingecko_market_chart_range_bitcoin_30d.json")}, seen)

    await CoinGeckoHistory(client, api_key=api_key, now=_clock()).history(
        "bitcoin", date(2026, 9, 19), date(2026, 10, 19)
    )

    assert seen[0].headers.get("x-cg-demo-api-key") == expected


async def test_coingecko_reports_an_unknown_coin_as_a_provider_error() -> None:
    client = _client({"/api/v3/coins/notacoin/market_chart/range": {}})

    with pytest.raises(ProviderError, match=r"coingecko.*unexpected payload"):
        await CoinGeckoHistory(client, now=_clock()).history(
            "notacoin", date(2026, 9, 19), date(2026, 10, 19)
        )


async def test_coingecko_rejects_a_malformed_coin_id_without_a_request() -> None:
    seen: list[httpx.Request] = []

    with pytest.raises(ProviderError, match="coingecko"):
        await CoinGeckoHistory(_client({}, seen), now=_clock()).history(
            "../simple/price", date(2026, 9, 19), date(2026, 10, 19)
        )
    assert seen == []


async def test_coingecko_has_no_live_quotes() -> None:
    with pytest.raises(ProviderError, match="coingecko"):
        await CoinGeckoHistory(_client({}), now=_clock()).latest(["bitcoin"])


def _data912_routes() -> dict[str, Any]:
    return {
        "/live/arg_bonds": _fixture("live_arg_bonds.json"),
        "/live/usa_stocks": _fixture("live_usa_stocks.json"),
    }


async def test_data912_maps_live_quotes_with_currency_and_price_basis() -> None:
    client = _client(_data912_routes())

    points = await Data912Prices(client, now=_clock()).latest(
        ["arg_bonds/AL30", "arg_bonds/AL30D", "usa_stocks/AAPL"]
    )

    al30, al30d, aapl = (
        points[r] for r in ("arg_bonds/AL30", "arg_bonds/AL30D", "usa_stocks/AAPL")
    )
    assert (al30.symbol, al30.price, al30.currency, al30.price_basis) == (
        "AL30",
        Decimal("85200.0"),
        Currency.ARS,
        100,
    )
    assert (al30.bid, al30.ask, al30.fetched_at) == (Decimal("85200.0"), Decimal("85210.0"), NOW)
    assert (al30d.currency, al30d.price_basis) == (Currency.USD, 100)
    assert (aapl.price, aapl.currency, aapl.price_basis) == (Decimal("342.57"), Currency.USD, 1)


async def test_data912_skips_a_requested_row_without_a_last_price() -> None:
    rows = [{**r, "c": 0} if r["symbol"] == "AL30D" else r for r in _fixture("live_arg_bonds.json")]
    client = _client({"/live/arg_bonds": rows})

    points = await Data912Prices(client, now=_clock()).latest(["arg_bonds/AL30", "arg_bonds/AL30D"])

    assert list(points) == ["arg_bonds/AL30"]


async def test_data912_reports_an_empty_side_of_the_book_as_missing() -> None:
    rows = [
        {**r, "px_bid": 0} if r["symbol"] == "AL30" else r for r in _fixture("live_arg_bonds.json")
    ]
    client = _client({"/live/arg_bonds": rows})

    points = await Data912Prices(client, now=_clock()).latest(["arg_bonds/AL30"])

    assert (points["arg_bonds/AL30"].bid, points["arg_bonds/AL30"].ask) == (
        None,
        Decimal("85210.0"),
    )


@pytest.mark.parametrize(
    "broken_panel",
    [
        [{**r, "c": 0} for r in _fixture("live_arg_bonds.json")],
        {"Error": "unavailable"},
    ],
)
async def test_data912_keeps_the_other_panels_when_one_panel_fails(broken_panel: Any) -> None:
    client = _client({**_data912_routes(), "/live/arg_bonds": broken_panel})

    points = await Data912Prices(client, now=_clock()).latest(["arg_bonds/AL30", "usa_stocks/AAPL"])

    assert list(points) == ["usa_stocks/AAPL"]


async def test_data912_skips_a_row_whose_symbol_is_not_text() -> None:
    rows = [{"symbol": ["AL30"], "c": 1}, *_fixture("live_arg_bonds.json")]
    client = _client({"/live/arg_bonds": rows})

    points = await Data912Prices(client, now=_clock()).latest(["arg_bonds/AL30"])

    assert list(points) == ["arg_bonds/AL30"]


async def test_data912_rejects_an_unknown_panel() -> None:
    with pytest.raises(ProviderError, match=r"data912.*panel"):
        await Data912Prices(_client({}), now=_clock()).latest(["arg_options/GFGC"])


async def test_data912_history_maps_daily_closes_inside_the_range() -> None:
    client = _client({"/historical/bonds/AL30": _fixture("historical_bonds_AL30.json")})

    points = await Data912Prices(client, now=_clock()).history(
        "arg_bonds/AL30", date(2026, 10, 14), date(2026, 10, 16)
    )

    assert [p.source_ts for p in points] == [
        datetime(2026, 10, d, 3, tzinfo=UTC) for d in (14, 15, 16)
    ]
    assert {(p.symbol, p.currency, p.price_basis) for p in points} == {("AL30", Currency.ARS, 100)}


@pytest.mark.parametrize("ref", ["arg_corp/YCAMO", "arg_notes/S30O6", "usa_stocks/AAPL"])
async def test_data912_has_no_history_outside_bonds_stocks_and_cedears(ref: str) -> None:
    with pytest.raises(ProviderError, match=r"data912.*history"):
        await Data912Prices(_client({}), now=_clock()).history(ref, date(2026, 1, 1), NOW.date())


async def test_data912_history_reports_an_unknown_ticker_as_a_provider_error() -> None:
    client = _client({"/historical/bonds/ZZ99": {"Error": "Nahh no tengo ese ticker loko"}})

    with pytest.raises(ProviderError, match=r"data912.*unexpected payload"):
        await Data912Prices(client, now=_clock()).history(
            "arg_bonds/ZZ99", date(2026, 1, 1), NOW.date()
        )


async def test_data912_history_rejects_a_malformed_symbol_without_a_request() -> None:
    seen: list[httpx.Request] = []

    with pytest.raises(ProviderError, match="data912"):
        await Data912Prices(_client({}, seen), now=_clock()).history(
            "arg_bonds/../live/mep", date(2026, 1, 1), NOW.date()
        )
    assert seen == []


def _kraken_all_invalid() -> tuple[dict[str, Any], Callable[[httpx.AsyncClient], Any]]:
    ticker = _fixture("kraken_ticker.json")
    for row in ticker["result"].values():
        row["c"] = ["0", "1"]
    return _kraken_routes(ticker), lambda c: KrakenTicker(c, now=_clock()).latest(["BTC", "ETH"])


def _data912_live_all_invalid() -> tuple[dict[str, Any], Callable[[httpx.AsyncClient], Any]]:
    rows = [{**r, "c": 0} for r in _fixture("live_arg_bonds.json")]
    return {"/live/arg_bonds": rows}, lambda c: Data912Prices(c, now=_clock()).latest(
        ["arg_bonds/AL30", "arg_bonds/AL30D"]
    )


def _data912_history_all_invalid() -> tuple[dict[str, Any], Callable[[httpx.AsyncClient], Any]]:
    rows = [{**r, "c": None} for r in _fixture("historical_bonds_AL30.json")]
    return {"/historical/bonds/AL30": rows}, lambda c: Data912Prices(c, now=_clock()).history(
        "arg_bonds/AL30", date(2026, 1, 1), NOW.date()
    )


@pytest.mark.parametrize(
    "case", [_kraken_all_invalid, _data912_live_all_invalid, _data912_history_all_invalid]
)
async def test_a_payload_whose_candidate_rows_all_fail_validation_is_a_provider_error(
    case: Callable[[], tuple[dict[str, Any], Callable[[httpx.AsyncClient], Any]]],
) -> None:
    routes, fetch = case()

    with pytest.raises(ProviderError, match="no valid rows"):
        await fetch(_client(routes))


async def test_kraken_reports_an_empty_side_of_the_book_as_missing() -> None:
    ticker = _fixture("kraken_ticker.json")
    ticker["result"]["XXBTZUSD"]["b"] = ["0", "0", "0"]
    client = _client(_kraken_routes(ticker))

    points = await KrakenTicker(client, now=_clock()).latest(["BTC"])

    assert (points["BTC"].bid, points["BTC"].ask) == (None, Decimal("81970.70000"))


async def test_coingecko_rejects_an_out_of_range_timestamp() -> None:
    route = "/api/v3/coins/bitcoin/market_chart/range"
    client = _client({route: {"prices": [[10**20, 81226.5]]}})

    with pytest.raises(ProviderError, match=r"coingecko.*unexpected payload"):
        await CoinGeckoHistory(client, now=_clock()).history(
            "bitcoin", date(2026, 9, 19), date(2026, 10, 19)
        )
