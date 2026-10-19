from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app

UNREACHABLE_DSN = "postgresql+asyncpg://leaky-user:leaky-pass@leaky-host.invalid:5432/leaky_db"
PROXY_SECRET = "proxy-secret-" + "x" * 32


@pytest.fixture
async def offline_client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url=SecretStr(UNREACHABLE_DSN), readyz_timeout_seconds=1.0))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client


async def test_healthz_returns_ok_without_touching_the_database(
    offline_client: httpx.AsyncClient,
) -> None:
    response = await offline_client.get("/api/v1/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_returns_503_problem_without_leaking_connection_details(
    offline_client: httpx.AsyncClient,
) -> None:
    response = await offline_client.get("/api/v1/readyz")

    body = response.json()
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert body["code"] == "DATABASE_UNAVAILABLE"
    assert body["request_id"]
    for secret in ("leaky-user", "leaky-pass", "leaky-host", "leaky_db", "asyncpg"):
        assert secret not in response.text


async def test_client_ip_debug_echoes_the_client_ip_headers_as_received(
    offline_client: httpx.AsyncClient,
) -> None:
    response = await offline_client.get(
        "/api/v1/ops/client-ip-debug",
        headers={"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.1, 10.0.0.1"},
    )

    body = response.json()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert body["rate_limit_key"] == "203.0.113.7"
    assert body["headers"]["cf-connecting-ip"] == "203.0.113.7"
    assert body["headers"]["x-forwarded-for"] == "198.51.100.1, 10.0.0.1"
    assert body["headers"]["x-vercel-forwarded-for"] is None
    assert body["proxy_verified"] is False
    assert set(body["headers"]) == {
        "cf-connecting-ip",
        "true-client-ip",
        "x-forwarded-for",
        "x-real-ip",
        "x-vercel-forwarded-for",
        "forwarded",
    }


async def test_client_ip_debug_reports_the_shared_bucket_without_a_cloudflare_ip(
    offline_client: httpx.AsyncClient,
) -> None:
    response = await offline_client.get("/api/v1/ops/client-ip-debug")

    assert response.json()["rate_limit_key"] == "unknown-client"


async def test_client_ip_debug_stays_out_of_the_public_api_schema(
    offline_client: httpx.AsyncClient,
) -> None:
    response = await offline_client.get("/openapi.json")

    assert "/api/v1/ops/client-ip-debug" not in response.json()["paths"]


@pytest.fixture
async def proxied_client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(
            database_url=SecretStr(UNREACHABLE_DSN), proxy_shared_secret=SecretStr(PROXY_SECRET)
        )
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_client_ip_debug_reports_a_verified_proxy_without_echoing_its_secret(
    proxied_client: httpx.AsyncClient,
) -> None:
    response = await proxied_client.get(
        "/api/v1/ops/client-ip-debug",
        headers={
            "CF-Connecting-IP": "203.0.113.7",
            "X-Proxy-Secret": PROXY_SECRET,
            "X-Vercel-Forwarded-For": "198.51.100.4",
        },
    )

    body = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert body["proxy_verified"] is True
    assert body["rate_limit_key"] == "198.51.100.4"
    assert PROXY_SECRET not in response.text


@pytest.mark.parametrize("headers", [{}, {"X-Proxy-Secret": "wrong-secret"}])
async def test_client_ip_debug_reports_an_unverified_proxy(
    proxied_client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await proxied_client.get(
        "/api/v1/ops/client-ip-debug",
        headers={"CF-Connecting-IP": "203.0.113.7", "X-Vercel-Forwarded-For": "198.51.100.4"}
        | headers,
    )

    body = response.json()
    assert body["proxy_verified"] is False
    assert body["rate_limit_key"] == "203.0.113.7"


async def test_client_ip_debug_never_verifies_a_proxy_without_a_configured_secret(
    offline_client: httpx.AsyncClient,
) -> None:
    response = await offline_client.get(
        "/api/v1/ops/client-ip-debug", headers={"X-Proxy-Secret": PROXY_SECRET}
    )

    assert response.json()["proxy_verified"] is False
