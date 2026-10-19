import asyncio
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from investment_tracker.auth.models import Currency
from investment_tracker.market.providers import base
from investment_tracker.market.providers.argentinadatos import (
    ArgentinaDatosFci,
    ArgentinaDatosHolidays,
    ArgentinaDatosMepHistory,
)
from investment_tracker.market.providers.base import FxQuote, HolidayKind, ProviderError
from investment_tracker.market.providers.data912 import Data912Mep
from investment_tracker.market.providers.dolarapi import DolarApiMep
from investment_tracker.market.providers.registry import create_http_client

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers"
NOW = datetime(2026, 10, 19, 19, 45, tzinfo=UTC)


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client(routes: dict[str, Any], status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"error": "Not found"})
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _clock() -> Callable[[], datetime]:
    return lambda: NOW


async def test_dolarapi_maps_the_mep_quote_with_its_source_timestamp() -> None:
    client = _client({"/v1/dolares/bolsa": _fixture("dolarapi_bolsa.json")})

    quote = await DolarApiMep(client, now=_clock()).latest()

    assert quote == FxQuote(
        buy=Decimal("1539.4"),
        sell=Decimal("1540.2"),
        source_ts=datetime(2026, 10, 19, 18, 57, tzinfo=UTC),
        fetched_at=NOW,
    )


async def test_dolarapi_reports_a_server_error_as_a_provider_error() -> None:
    client = _client({"/v1/dolares/bolsa": {}}, status=503)

    with pytest.raises(ProviderError, match=r"dolarapi.*503"):
        await DolarApiMep(client, now=_clock()).latest()


async def test_dolarapi_reports_a_malformed_payload_as_a_provider_error() -> None:
    client = _client({"/v1/dolares/bolsa": {"compra": "n/a"}})

    with pytest.raises(ProviderError, match=r"dolarapi.*unexpected payload"):
        await DolarApiMep(client, now=_clock()).latest()


async def test_dolarapi_reports_a_timeout_as_a_provider_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))

    with pytest.raises(ProviderError, match=r"dolarapi.*ConnectTimeout"):
        await DolarApiMep(client, now=_clock()).latest()


async def test_data912_mep_uses_the_al30_implied_rate_without_a_source_timestamp() -> None:
    client = _client({"/live/mep": _fixture("live_mep.json")})

    quote = await Data912Mep(client, now=_clock()).latest()

    assert quote == FxQuote(
        buy=Decimal("1540.5894"), sell=Decimal("1541.0488"), source_ts=None, fetched_at=NOW
    )


async def test_data912_mep_fails_when_the_al30_row_is_missing() -> None:
    rows = [row for row in _fixture("live_mep.json") if row["ticker"] != "AL30"]
    client = _client({"/live/mep": rows})

    with pytest.raises(ProviderError, match=r"data912.*AL30"):
        await Data912Mep(client, now=_clock()).latest()


async def test_argentinadatos_holidays_maps_date_kind_and_name() -> None:
    client = _client({"/v1/feriados/2026": _fixture("argentinadatos_feriados_2026.json")})

    holidays = await ArgentinaDatosHolidays(client).holidays(2026)

    assert len(holidays) == 20
    assert holidays[0].day == date(2026, 1, 1)
    assert holidays[0].kind is HolidayKind.INAMOVIBLE
    assert {h.kind for h in holidays} >= {HolidayKind.TRASLADABLE, HolidayKind.PUENTE}


async def test_argentinadatos_mep_history_keeps_weekdays_inside_the_range() -> None:
    client = _client(
        {"/v1/cotizaciones/dolares/bolsa": _fixture("argentinadatos_dolares_bolsa.json")}
    )

    rates = await ArgentinaDatosMepHistory(client).history(date(2026, 10, 9), date(2026, 10, 13))

    assert [r.day for r in rates] == [date(2026, 10, 9), date(2026, 10, 12), date(2026, 10, 13)]
    assert rates[0].buy > 0
    assert rates[0].sell > 0


async def test_argentinadatos_fci_returns_the_unit_value_of_each_requested_fund() -> None:
    client = _client(
        {
            "/v1/finanzas/fci/mercadoDinero/ultimo": _fixture(
                "argentinadatos_fci_mercadoDinero_ultimo.json"
            )
        }
    )

    points = await ArgentinaDatosFci(client, now=_clock()).latest(
        ["mercadoDinero/1810 Ahorro", "mercadoDinero/Unknown Fund"]
    )

    assert list(points) == ["mercadoDinero/1810 Ahorro"]
    point = points["mercadoDinero/1810 Ahorro"]
    assert (point.price, point.currency) == (Decimal("242182.465"), Currency.ARS)
    assert point.source_ts == datetime(2026, 10, 16, 3, tzinfo=UTC)
    assert point.fetched_at == NOW


async def test_argentinadatos_fci_skips_funds_whose_name_is_ambiguous() -> None:
    rows = _fixture("argentinadatos_fci_rentaFija_ultimo.json")
    duplicated = rows[0]["fondo"]
    client = _client({"/v1/finanzas/fci/rentaFija/ultimo": rows})

    points = await ArgentinaDatosFci(client, now=_clock()).latest([f"rentaFija/{duplicated}"])

    assert points == {}


async def test_argentinadatos_fci_rejects_an_unknown_category() -> None:
    client = _client({})

    with pytest.raises(ProviderError, match=r"argentinadatos.*otros"):
        await ArgentinaDatosFci(client, now=_clock()).latest(["otros/Plazo Fijo"])


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", "0", "-1", "1E-999999", "1E25"])
async def test_a_non_finite_non_positive_or_unbounded_amount_is_rejected(amount: str) -> None:
    quote = {**_fixture("dolarapi_bolsa.json"), "compra": amount}
    client = _client({"/v1/dolares/bolsa": quote})

    with pytest.raises(ProviderError, match=r"dolarapi.*unexpected payload"):
        await DolarApiMep(client, now=_clock()).latest()


def _dolarapi_inverted() -> tuple[str, dict[str, Any], Callable[[httpx.AsyncClient], Any]]:
    quote = {**_fixture("dolarapi_bolsa.json"), "compra": 1600, "venta": 1500}
    return "/v1/dolares/bolsa", quote, lambda c: DolarApiMep(c, now=_clock()).latest()


def _data912_inverted() -> tuple[str, Any, Callable[[httpx.AsyncClient], Any]]:
    rows = [
        {**r, "bid": 1600, "ask": 1500} if r["ticker"] == "AL30" else r
        for r in _fixture("live_mep.json")
    ]
    return "/live/mep", rows, lambda c: Data912Mep(c, now=_clock()).latest()


def _mep_history_inverted() -> tuple[str, Any, Callable[[httpx.AsyncClient], Any]]:
    rows = [{"casa": "bolsa", "compra": 1600, "venta": 1500, "fecha": "2026-10-13"}]
    return (
        "/v1/cotizaciones/dolares/bolsa",
        rows,
        lambda c: ArgentinaDatosMepHistory(c).history(date(2026, 10, 1), date(2026, 10, 31)),
    )


@pytest.mark.parametrize("case", [_dolarapi_inverted, _data912_inverted, _mep_history_inverted])
async def test_an_fx_rate_whose_sell_is_below_its_buy_is_rejected(
    case: Callable[[], tuple[str, Any, Callable[[httpx.AsyncClient], Any]]],
) -> None:
    path, body, fetch = case()
    client = _client({path: body})

    with pytest.raises(ProviderError, match="unexpected payload"):
        await fetch(client)


async def test_a_response_larger_than_the_size_cap_is_rejected() -> None:
    padding = " " * (2 * 1024 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"[]" + padding.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderError, match=r"argentinadatos.*exceeds"):
        await ArgentinaDatosHolidays(client).holidays(2026)


@pytest.mark.parametrize(
    "name", ["x" * 201, "Carnaval\x1b[31m", "Navidad\nfake log line", "Navidad\x85"]
)
async def test_an_unbounded_or_control_character_text_field_is_rejected(name: str) -> None:
    rows = [{"fecha": "2026-12-25", "tipo": "inamovible", "nombre": name}]
    client = _client({"/v1/feriados/2026": rows})

    with pytest.raises(ProviderError, match="unexpected payload"):
        await ArgentinaDatosHolidays(client).holidays(2026)


async def test_a_payload_list_longer_than_the_item_cap_is_rejected() -> None:
    rows = [{"fecha": "2026-12-25", "tipo": "inamovible", "nombre": "Navidad"}] * 10_001
    client = _client({"/v1/feriados/2026": rows})

    with pytest.raises(ProviderError, match="unexpected payload"):
        await ArgentinaDatosHolidays(client).holidays(2026)


async def test_a_provider_error_does_not_echo_the_reference_and_stays_short() -> None:
    client = _client({})
    category = "c" * 500

    with pytest.raises(ProviderError) as raised:
        await ArgentinaDatosFci(client, now=_clock()).latest([f"{category}/Secret Fund"])

    assert "Secret Fund" not in str(raised.value)
    assert len(str(raised.value)) <= 256


async def test_the_shared_http_client_does_not_follow_redirects() -> None:
    async with create_http_client() as client:
        assert client.follow_redirects is False


async def test_an_fx_rate_beyond_the_fx_column_range_is_rejected() -> None:
    quote = {**_fixture("dolarapi_bolsa.json"), "compra": "1E14", "venta": "2E14"}
    client = _client({"/v1/dolares/bolsa": quote})

    with pytest.raises(ProviderError, match=r"dolarapi.*unexpected payload"):
        await DolarApiMep(client, now=_clock()).latest()


async def test_data912_mep_ignores_an_unquoted_row_other_than_al30() -> None:
    rows = [
        r if r["ticker"] == "AL30" else {**r, "bid": 0, "ask": 0} for r in _fixture("live_mep.json")
    ]
    client = _client({"/live/mep": rows})

    quote = await Data912Mep(client, now=_clock()).latest()

    assert (quote.buy, quote.sell) == (Decimal("1540.5894"), Decimal("1541.0488"))


async def test_data912_mep_fails_when_the_al30_row_is_unquoted() -> None:
    rows = [{**r, "bid": 0} if r["ticker"] == "AL30" else r for r in _fixture("live_mep.json")]
    client = _client({"/live/mep": rows})

    with pytest.raises(ProviderError, match=r"data912.*AL30"):
        await Data912Mep(client, now=_clock()).latest()


async def test_a_response_slower_than_the_total_deadline_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(base, "REQUEST_DEADLINE_SECONDS", 0.05)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))

    with pytest.raises(ProviderError, match=r"argentinadatos.*deadline"):
        await ArgentinaDatosHolidays(client).holidays(2026)


async def test_the_shared_http_client_asks_for_uncompressed_responses() -> None:
    async with create_http_client() as client:
        assert client.headers["Accept-Encoding"] == "identity"
