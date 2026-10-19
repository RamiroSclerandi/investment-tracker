import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from investment_tracker.auth.models import Currency
from investment_tracker.market.providers.argentinadatos import (
    ArgentinaDatosFci,
    ArgentinaDatosHolidays,
    ArgentinaDatosMepHistory,
)
from investment_tracker.market.providers.base import FxQuote, HolidayKind, ProviderError
from investment_tracker.market.providers.data912 import Data912Mep
from investment_tracker.market.providers.dolarapi import DolarApiMep

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
