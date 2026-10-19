import json
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from fastapi import FastAPI
from pydantic import SecretStr

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
