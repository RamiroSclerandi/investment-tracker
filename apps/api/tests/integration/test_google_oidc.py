import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import structlog
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from investment_tracker.auth.passwords import hash_password
from investment_tracker.auth.tokens import hash_token
from investment_tracker.core.rate_limit import (
    forgot_client_email_limiter,
    forgot_email_limiter,
    limiter,
    login_limiter,
)
from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app
from tests.google_fakes import (
    CALLBACK_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    START_URL,
    FakeGoogle,
    cookie_attributes,
)
from tests.integration.conftest import WEB_BASE_URL, RecordingEmailSender

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"
PASSWORD_HASH = hash_password(PASSWORD)
CLIENT_IP = {"CF-Connecting-IP": "203.0.113.7"}
COMPLETE_URL = f"{WEB_BASE_URL}/auth/complete"
FAILED_URL = f"{WEB_BASE_URL}/auth/complete#error=oauth_failed"
EMAIL = "ana@example.com"


@pytest.fixture
def fake_google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def app(
    migrated_database_url: str, emails: RecordingEmailSender, fake_google: FakeGoogle
) -> FastAPI:
    limiter.reset()
    login_limiter.reset()
    forgot_client_email_limiter.reset()
    forgot_email_limiter.reset()
    settings = Settings(
        database_url=SecretStr(migrated_database_url),
        web_base_url=WEB_BASE_URL,
        google_client_id=CLIENT_ID,
        google_client_secret=SecretStr(CLIENT_SECRET),
        _env_file=None,
    )
    return create_app(settings, email_sender=emails, google=fake_google.client())


async def _start(client: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    response = await client.get(START_URL, headers=CLIENT_IP)
    query = dict(parse_qsl(urlsplit(response.headers["location"]).query))
    return query, cookie_attributes(response.headers["set-cookie"])[1]


async def _sign_in(
    client: httpx.AsyncClient,
    fake_google: FakeGoogle,
    *,
    cookie: str | None = None,
    params: dict[str, str | None] | None = None,
) -> httpx.Response:
    query, started_cookie = await _start(client)
    if not fake_google.nonce:
        fake_google.nonce = query["nonce"]
    merged = {"code": "auth-code", "state": query["state"], **(params or {})}
    sent_cookie = started_cookie if cookie is None else cookie
    return await client.get(
        CALLBACK_URL,
        params={name: value for name, value in merged.items() if value is not None},
        headers={**CLIENT_IP, "Cookie": f"it_oidc={sent_cookie}"},
    )


def _set_cookies(response: httpx.Response) -> dict[str, tuple[str, set[str]]]:
    cookies = {}
    for header in response.headers.get_list("set-cookie"):
        name, value, attributes = cookie_attributes(header)
        cookies[name] = (value, attributes)
    return cookies


async def _create_user(
    engine: AsyncEngine,
    *,
    password_hash: str | None = PASSWORD_HASH,
    is_verified: bool = True,
    is_active: bool = True,
) -> uuid.UUID:
    async with engine.begin() as connection:
        user_id: uuid.UUID = await connection.scalar(
            text(
                "INSERT INTO app.users (email, password_hash, email_verified_at, display_name,"
                " is_active) VALUES (:email, :hash, :verified, 'Local Ana', :active)"
                " RETURNING id"
            ),
            {
                "email": EMAIL,
                "hash": password_hash,
                "verified": datetime.now(UTC) if is_verified else None,
                "active": is_active,
            },
        )
    return user_id


async def _link(engine: AsyncEngine, user_id: uuid.UUID, subject: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO app.oauth_accounts (user_id, provider, provider_subject, email)"
                " VALUES (:user_id, 'google', :subject, :email)"
            ),
            {"user_id": user_id, "subject": subject, "email": EMAIL},
        )


async def _rows(engine: AsyncEngine, query: str, **params: Any) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(text(query), params)
        return [dict(row) for row in result.mappings().all()]


async def _users(engine: AsyncEngine) -> list[dict[str, Any]]:
    return await _rows(
        engine,
        "SELECT id, email, password_hash, email_verified_at, display_name FROM app.users",
    )


async def _oauth_accounts(engine: AsyncEngine) -> list[dict[str, Any]]:
    return await _rows(
        engine, "SELECT user_id, provider::text, provider_subject, email FROM app.oauth_accounts"
    )


async def _refresh(client: httpx.AsyncClient, refresh_token: str) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/refresh",
        headers={
            **CLIENT_IP,
            "X-Requested-With": "investment-tracker",
            "Cookie": f"it_rt={refresh_token}",
        },
    )


def _assert_succeeded(response: httpx.Response) -> str:
    assert response.status_code == httpx.codes.FOUND
    assert response.headers["location"] == COMPLETE_URL
    assert response.headers["cache-control"] == "no-store"
    cookies = _set_cookies(response)
    assert cookies["it_oidc"][1] >= {"max-age=0", "path=/api/v1/auth/google"}
    refresh_token, attributes = cookies["it_rt"]
    assert {"httponly", "secure", "samesite=strict", "path=/api/v1/auth"} <= attributes
    return refresh_token


def _assert_failed(response: httpx.Response) -> None:
    assert response.status_code == httpx.codes.FOUND
    assert response.headers["location"] == FAILED_URL
    assert response.headers["cache-control"] == "no-store"
    cookies = _set_cookies(response)
    assert "it_rt" not in cookies
    assert cookies["it_oidc"][1] >= {"max-age=0", "path=/api/v1/auth/google"}


async def test_a_new_google_user_is_created_verified_and_signed_in(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    fake_google: FakeGoogle,
    emails: RecordingEmailSender,
) -> None:
    response = await _sign_in(client, fake_google)

    assert emails.sent == []
    refresh_token = _assert_succeeded(response)
    [user] = await _users(engine)
    assert user["email"] == EMAIL
    assert user["password_hash"] is None
    assert user["email_verified_at"] is not None
    assert user["display_name"] == "Ana Google"
    assert await _oauth_accounts(engine) == [
        {
            "user_id": user["id"],
            "provider": "google",
            "provider_subject": "google-subject-1",
            "email": EMAIL,
        }
    ]
    refreshed = await _refresh(client, refresh_token)
    assert refreshed.status_code == httpx.codes.OK
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert me.json()["email"] == EMAIL


@pytest.mark.parametrize("name", [None, " \n\u2028 "])
async def test_a_new_user_without_a_usable_google_name_is_named_after_the_email(
    client: httpx.AsyncClient, engine: AsyncEngine, fake_google: FakeGoogle, name: str | None
) -> None:
    fake_google.overrides = {"name": name}

    _assert_succeeded(await _sign_in(client, fake_google))

    [user] = await _users(engine)
    assert user["display_name"] == "ana"


async def test_an_existing_google_account_signs_in_its_user(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    fake_google: FakeGoogle,
    emails: RecordingEmailSender,
) -> None:
    user_id = await _create_user(engine)
    await _link(engine, user_id, "google-subject-1")
    fake_google.overrides = {"email": "renamed@example.com", "name": "Other Name"}

    _assert_succeeded(await _sign_in(client, fake_google))

    assert emails.sent == []
    [user] = await _users(engine)
    assert user["id"] == user_id
    assert user["display_name"] == "Local Ana"
    assert user["password_hash"] == PASSWORD_HASH
    assert len(await _oauth_accounts(engine)) == 1


async def test_a_verified_local_user_is_linked_without_changing_password_or_name(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    fake_google: FakeGoogle,
    emails: RecordingEmailSender,
) -> None:
    user_id = await _create_user(engine)

    _assert_succeeded(await _sign_in(client, fake_google))

    [user] = await _users(engine)
    assert user["id"] == user_id
    assert user["password_hash"] == PASSWORD_HASH
    assert user["display_name"] == "Local Ana"
    assert [account["user_id"] for account in await _oauth_accounts(engine)] == [user_id]
    # Linking a verified account happened without any password proof, so the mailbox learns.
    [notification] = emails.sent
    assert notification.to == EMAIL
    assert notification.subject == "Vinculaste Google a tu cuenta"
    assert "#token=" not in notification.text


async def test_password_login_still_works_for_a_linked_verified_user(
    client: httpx.AsyncClient, engine: AsyncEngine, fake_google: FakeGoogle
) -> None:
    await _create_user(engine)
    _assert_succeeded(await _sign_in(client, fake_google))

    response = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers=CLIENT_IP
    )

    assert response.status_code == httpx.codes.OK
    assert response.json()["token_type"] == "Bearer"


async def test_an_unverified_local_user_is_claimed_by_the_google_mailbox_owner(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    fake_google: FakeGoogle,
    emails: RecordingEmailSender,
) -> None:
    user_id = await _create_user(engine, is_verified=False)
    now = datetime.now(UTC)
    async with engine.begin() as connection:
        for token in ("pending-1", "pending-2"):
            await connection.execute(
                text(
                    "INSERT INTO app.email_tokens (user_id, purpose, token_hash, expires_at)"
                    " VALUES (:user_id, 'verify_email', :hash, :expires)"
                ),
                {"user_id": user_id, "hash": hash_token(token), "expires": now + timedelta(days=1)},
            )
        await connection.execute(
            text(
                "INSERT INTO app.refresh_tokens (user_id, family_id, token_hash, expires_at)"
                " VALUES (:user_id, :family, :hash, :expires)"
            ),
            {
                "user_id": user_id,
                "family": uuid.uuid4(),
                "hash": hash_token("squatter-session"),
                "expires": now + timedelta(days=1),
            },
        )

    refresh_token = _assert_succeeded(await _sign_in(client, fake_google))

    assert emails.sent == []
    [user] = await _users(engine)
    assert user["id"] == user_id
    assert user["password_hash"] is None
    assert user["email_verified_at"] is not None
    assert user["display_name"] == "Ana Google"
    tokens = await _rows(engine, "SELECT used_at FROM app.email_tokens")
    assert len(tokens) == 2
    assert all(token["used_at"] is not None for token in tokens)
    sessions = await _rows(engine, "SELECT token_hash, revoked_at FROM app.refresh_tokens")
    revoked = {row["token_hash"]: row["revoked_at"] is not None for row in sessions}
    assert revoked == {hash_token("squatter-session"): True, hash_token(refresh_token): False}
    assert (await _refresh(client, "squatter-session")).status_code == httpx.codes.UNAUTHORIZED
    assert [account["user_id"] for account in await _oauth_accounts(engine)] == [user_id]


async def test_an_unverified_local_user_keeps_its_name_when_google_sends_none(
    client: httpx.AsyncClient, engine: AsyncEngine, fake_google: FakeGoogle
) -> None:
    await _create_user(engine, is_verified=False)
    fake_google.overrides = {"name": "\x00"}

    _assert_succeeded(await _sign_in(client, fake_google))

    [user] = await _users(engine)
    assert user["display_name"] == "Local Ana"
    assert user["password_hash"] is None


async def test_an_inactive_user_matching_the_email_is_never_linked(
    client: httpx.AsyncClient, engine: AsyncEngine, fake_google: FakeGoogle
) -> None:
    await _create_user(engine, is_active=False)

    _assert_failed(await _sign_in(client, fake_google))

    assert await _oauth_accounts(engine) == []
    assert await _rows(engine, "SELECT id FROM app.refresh_tokens") == []


async def test_an_inactive_user_cannot_sign_in_through_a_linked_google_account(
    client: httpx.AsyncClient, engine: AsyncEngine, fake_google: FakeGoogle
) -> None:
    user_id = await _create_user(engine, is_active=False)
    await _link(engine, user_id, "google-subject-1")

    _assert_failed(await _sign_in(client, fake_google))

    assert await _rows(engine, "SELECT id FROM app.refresh_tokens") == []


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("missing_cookie", "invalid_state_cookie"),
        ("forged_cookie", "invalid_state_cookie"),
        ("state_mismatch", "state_mismatch"),
        ("missing_state", "state_mismatch"),
        ("google_error", "provider_error"),
        ("missing_code", "provider_error"),
        ("exchange_rejected", "token_exchange_failed"),
        ("wrong_audience", "invalid_id_token"),
        ("nonce_mismatch", "nonce_mismatch"),
        ("unverified_google_email", "email_not_verified"),
    ],
)
async def test_every_callback_failure_redirects_generically_and_creates_nothing(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    fake_google: FakeGoogle,
    case: str,
    reason: str,
) -> None:
    kwargs: dict[str, Any] = {}
    match case:
        case "missing_cookie":
            kwargs["cookie"] = ""
        case "forged_cookie":
            kwargs["cookie"] = "eyJhbGciOiJub25lIn0.e30."
        case "state_mismatch":
            kwargs["params"] = {"state": "attacker-state"}
        case "missing_state":
            kwargs["params"] = {"state": None}
        case "google_error":
            kwargs["params"] = {"code": None, "error": "access_denied"}
        case "missing_code":
            kwargs["params"] = {"code": None}
        case "exchange_rejected":
            fake_google.token_status = httpx.codes.BAD_REQUEST
        case "wrong_audience":
            fake_google.overrides = {"aud": "another-client"}
        case "nonce_mismatch":
            fake_google.nonce = "replayed-nonce"
        case "unverified_google_email":
            fake_google.overrides = {"email_verified": False}

    with structlog.testing.capture_logs() as logs:
        response = await _sign_in(client, fake_google, **kwargs)

    _assert_failed(response)
    assert await _users(engine) == []
    assert await _oauth_accounts(engine) == []
    failures = [entry for entry in logs if entry["event"] == "google_sign_in_failed"]
    assert failures == [
        {"event": "google_sign_in_failed", "reason": reason, "log_level": "warning"}
    ]


async def test_a_state_cookie_is_bound_to_its_own_flow(
    client: httpx.AsyncClient, engine: AsyncEngine, fake_google: FakeGoogle
) -> None:
    _, first_cookie = await _start(client)

    response = await _sign_in(client, fake_google, cookie=first_cookie)

    _assert_failed(response)
    assert await _users(engine) == []


async def test_concurrent_first_sign_ins_create_one_user_and_one_link(
    client: httpx.AsyncClient, engine: AsyncEngine, fake_google: FakeGoogle
) -> None:
    starts = [await _start(client), await _start(client)]

    # With no fixed nonce the fake echoes the code as the nonce, so each flow gets its own token.
    responses = await asyncio.gather(
        *(
            client.get(
                CALLBACK_URL,
                params={"code": query["nonce"], "state": query["state"]},
                headers={**CLIENT_IP, "Cookie": f"it_oidc={cookie}"},
            )
            for query, cookie in starts
        )
    )

    for response in responses:
        _assert_succeeded(response)
    assert len(await _users(engine)) == 1
    assert len(await _oauth_accounts(engine)) == 1


async def test_the_callback_allows_ten_requests_per_minute_per_client_ip(
    client: httpx.AsyncClient,
) -> None:
    for _ in range(10):
        response = await client.get(CALLBACK_URL, headers=CLIENT_IP)
        assert response.status_code == httpx.codes.FOUND

    limited = await client.get(CALLBACK_URL, headers=CLIENT_IP)

    assert limited.status_code == httpx.codes.TOO_MANY_REQUESTS
    cookies = _set_cookies(limited)
    assert cookies["it_oidc"][1] >= {"max-age=0", "path=/api/v1/auth/google"}
