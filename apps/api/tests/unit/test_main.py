import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from investment_tracker.core.email import SmtpEmailSender, UnconfiguredEmailSender
from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app

DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/test"


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


def test_email_sender_defaults_to_unconfigured_without_an_smtp_url() -> None:
    settings = Settings(database_url=SecretStr(DATABASE_URL), _env_file=None)

    app = create_app(settings)

    assert isinstance(app.state.email_sender, UnconfiguredEmailSender)


def test_email_sender_defaults_to_smtp_when_an_smtp_url_is_set() -> None:
    settings = Settings(
        database_url=SecretStr(DATABASE_URL),
        smtp_url=SecretStr("smtp://mailpit:1025"),
        _env_file=None,
    )

    app = create_app(settings)

    assert isinstance(app.state.email_sender, SmtpEmailSender)
