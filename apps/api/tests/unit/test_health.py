from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app

UNREACHABLE_DSN = "postgresql+asyncpg://leaky-user:leaky-pass@leaky-host.invalid:5432/leaky_db"


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


async def test_the_client_ip_debug_endpoint_is_not_served(
    offline_client: httpx.AsyncClient,
) -> None:
    response = await offline_client.get("/api/v1/ops/client-ip-debug")

    assert response.status_code == 404
