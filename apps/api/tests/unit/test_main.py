import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app


def production_app() -> FastAPI:
    return create_app(
        Settings(
            database_url=SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test"),
            environment="production",
        )
    )


async def test_docs_are_disabled_in_production() -> None:
    transport = httpx.ASGITransport(app=production_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404


def test_openapi_schema_is_still_exportable_in_production() -> None:
    schema = production_app().openapi()

    assert schema["info"]["title"] == "Investment Tracker"


async def test_docs_are_served_outside_production(client: httpx.AsyncClient) -> None:
    assert (await client.get("/openapi.json")).status_code == 200
