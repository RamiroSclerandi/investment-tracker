import json
import uuid
from datetime import date

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from fastapi import FastAPI
from pydantic import SecretStr

from investment_tracker import main
from investment_tracker.auth.jwt import AccessTokens
from investment_tracker.core.email import SmtpEmailSender, UnconfiguredEmailSender
from investment_tracker.core.gmail import GmailApiEmailSender
from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app

DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/test"


def _ed25519_pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


def production_app() -> FastAPI:
    return create_app(
        Settings(
            database_url=SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test"),
            environment="production",
            jwt_private_key=SecretStr(_ed25519_pem(Ed25519PrivateKey.generate())),
            smtp_url=SecretStr("smtps://user:pass@smtp.example.com:465"),
            web_base_url="https://app.example.com",
            proxy_shared_secret=SecretStr("p" * 32),
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


def test_openapi_documents_validation_errors_as_problem_json() -> None:
    schema = production_app().openapi()

    login_422 = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]["422"]
    assert list(login_422["content"]) == ["application/problem+json"]
    problem_ref = login_422["content"]["application/problem+json"]["schema"]["$ref"]
    problem = schema["components"]["schemas"][problem_ref.rsplit("/", 1)[1]]
    assert set(problem["properties"]) == {
        "type",
        "title",
        "status",
        "detail",
        "code",
        "request_id",
        "errors",
    }
    assert "HTTPValidationError" not in json.dumps(schema)
    assert "ValidationError" not in schema["components"]["schemas"]


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


def test_email_sender_prefers_the_gmail_api_over_smtp() -> None:
    settings = Settings(
        database_url=SecretStr(DATABASE_URL),
        smtp_url=SecretStr("smtp://mailpit:1025"),
        gmail_client_id="gmail-client",
        gmail_client_secret=SecretStr("-".join(["gmail", "secret"])),
        gmail_refresh_token=SecretStr("-".join(["gmail", "refresh"])),
        gmail_sender="owner@gmail.com",
        _env_file=None,
    )

    app = create_app(settings)

    assert isinstance(app.state.email_sender, GmailApiEmailSender)


def test_access_tokens_are_signed_with_the_configured_key() -> None:
    key = Ed25519PrivateKey.generate()
    settings = Settings(
        database_url=SecretStr(DATABASE_URL),
        jwt_private_key=SecretStr(_ed25519_pem(key)),
        _env_file=None,
    )
    user_id = uuid.uuid4()

    app = create_app(settings)

    token, _ = app.state.access_tokens.issue(user_id)
    verifier = AccessTokens(key, issuer=settings.jwt_issuer, audience=settings.jwt_audience)
    assert verifier.decode(token) == user_id


async def test_an_ephemeral_signing_key_is_generated_outside_production_without_logging_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(database_url=SecretStr(DATABASE_URL), _env_file=None)
    user_id = uuid.uuid4()

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        token, _ = app.state.access_tokens.issue(user_id)

    assert app.state.access_tokens.decode(token) == user_id
    output = capsys.readouterr().out
    assert "jwt_signing_key_ephemeral" in output
    assert "PRIVATE KEY" not in output


async def test_the_lifespan_builds_the_market_providers_on_one_http_client_and_closes_it() -> None:
    app = create_app(Settings(database_url=SecretStr(DATABASE_URL), _env_file=None))

    async with app.router.lifespan_context(app):
        client = app.state.http_client
        providers = app.state.providers
        assert not client.is_closed
        assert {providers.mep.name, providers.mep_fallback.name} == {"dolarapi", "data912"}

    assert client.is_closed


async def test_the_lifespan_wires_the_price_providers_and_the_coingecko_demo_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"prices": [[1789858800000, 81226.5]]})

    monkeypatch.setattr(
        main,
        "create_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    settings = Settings(
        database_url=SecretStr(DATABASE_URL),
        coingecko_api_key=SecretStr("demo-key"),
        _env_file=None,
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        providers = app.state.providers
        assert (providers.crypto_live.name, providers.prices.name) == ("kraken", "data912")
        await providers.crypto_history.history("bitcoin", date(2026, 10, 1), date(2026, 10, 2))

    assert seen[0].headers["x-cg-demo-api-key"] == "demo-key"
