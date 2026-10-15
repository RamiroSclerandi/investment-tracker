import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from investment_tracker.auth.passwords import hash_password, verify_password_async
from investment_tracker.auth.tokens import hash_token

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"
WRONG_PASSWORD = "incorrect horse battery"
SHORT_PASSWORD = "x"
EMPTY_PASSWORD = ""
TOO_LONG_PASSWORD = "x" * 129
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
CLIENT_IP = {"CF-Connecting-IP": "203.0.113.7"}
PASSWORD_HASH = hash_password(PASSWORD)


async def _create_user(
    engine: AsyncEngine,
    email: str = "ana@example.com",
    *,
    password_hash: str | None = PASSWORD_HASH,
    is_verified: bool = True,
    is_active: bool = True,
) -> uuid.UUID:
    async with engine.begin() as connection:
        user_id: uuid.UUID = await connection.scalar(
            text(
                "INSERT INTO app.users (email, password_hash, email_verified_at, display_name,"
                " is_active) VALUES (:email, :hash, :verified, 'Ana', :active) RETURNING id"
            ),
            {
                "email": email,
                "hash": password_hash,
                "verified": datetime.now(UTC) if is_verified else None,
                "active": is_active,
            },
        )
    return user_id


async def _refresh_tokens(engine: AsyncEngine, user_id: uuid.UUID) -> list[dict[str, object]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT token_hash, family_id, expires_at, rotated_at, revoked_at, user_agent, ip"
                " FROM app.refresh_tokens WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        )
        return [dict(row) for row in rows.mappings().all()]


async def _login(
    client: httpx.AsyncClient,
    email: str = "ana@example.com",
    password: str = PASSWORD,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        LOGIN_URL, json={"email": email, "password": password}, headers=headers or CLIENT_IP
    )


def _cookie_attributes(set_cookie: str) -> tuple[str, str, set[str]]:
    pair, *attributes = (part.strip() for part in set_cookie.split(";"))
    name, _, value = pair.partition("=")
    return name, value, {attribute.lower() for attribute in attributes}


async def test_a_verified_user_logs_in_and_gets_an_access_token_and_a_refresh_cookie(
    client: httpx.AsyncClient, engine: AsyncEngine, app: FastAPI
) -> None:
    user_id = await _create_user(engine)

    response = await _login(client, headers={**CLIENT_IP, "User-Agent": "Firefox/140"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 900
    assert app.state.access_tokens.decode(body["access_token"]) == user_id
    name, value, attributes = _cookie_attributes(response.headers["set-cookie"])
    assert name == "it_rt"
    assert attributes == {
        "httponly",
        "secure",
        "samesite=strict",
        "path=/api/v1/auth",
        "max-age=2592000",
    }
    [stored] = await _refresh_tokens(engine, user_id)
    assert stored["token_hash"] == hash_token(value)
    assert stored["token_hash"] != value
    assert isinstance(stored["expires_at"], datetime)
    remaining = stored["expires_at"] - datetime.now(UTC)
    assert timedelta(days=29, hours=23) < remaining <= timedelta(days=30)
    assert stored["rotated_at"] is None
    assert stored["revoked_at"] is None
    assert stored["user_agent"] == "Firefox/140"
    assert stored["ip"] == "203.0.113.7"
    assert response.headers["cache-control"] == "no-store"


async def test_every_login_starts_a_new_token_family(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)

    await _login(client)
    await _login(client)

    rows = await _refresh_tokens(engine, user_id)
    assert len(rows) == 2
    assert rows[0]["family_id"] != rows[1]["family_id"]


async def test_login_matches_the_email_case_insensitively(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await _create_user(engine)

    response = await _login(client, email="Ana@Example.com")

    assert response.status_code == 200


async def test_login_stores_a_truncated_user_agent_and_no_ip_without_a_valid_client_ip(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)

    response = await _login(
        client, headers={"User-Agent": "x" * 300, "X-Forwarded-For": "198.51.100.1"}
    )

    assert response.status_code == 200
    [stored] = await _refresh_tokens(engine, user_id)
    assert stored["user_agent"] == "x" * 256
    assert stored["ip"] is None


async def test_an_unverified_user_with_the_right_password_is_told_to_verify(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine, is_verified=False)

    response = await _login(client)

    assert response.status_code == 403
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"
    assert "set-cookie" not in response.headers
    assert await _refresh_tokens(engine, user_id) == []


async def test_an_unverified_user_with_the_wrong_password_gets_invalid_credentials(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await _create_user(engine, is_verified=False)

    response = await _login(client, password=WRONG_PASSWORD)

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_login_is_rejected_when_the_password_changes_while_it_is_checked(
    client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _create_user(engine)

    async def verify_then_change_password(password_hash: str, password: str) -> bool:
        result = await verify_password_async(password_hash, password)
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE app.users SET password_hash = :hash WHERE id = :user_id"),
                {"hash": hash_password(WRONG_PASSWORD), "user_id": user_id},
            )
        return result

    monkeypatch.setattr(
        "investment_tracker.auth.service.verify_password_async", verify_then_change_password
    )

    response = await _login(client)

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert "set-cookie" not in response.headers
    assert await _refresh_tokens(engine, user_id) == []


def _comparable(response: httpx.Response) -> tuple[int, dict[str, object]]:
    body = response.json()
    body.pop("request_id")
    return response.status_code, body


async def test_every_credential_failure_gets_the_same_response(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await _create_user(engine, "ana@example.com")
    await _create_user(engine, "nopass@example.com", password_hash=None)
    await _create_user(engine, "inactive@example.com", is_active=False)

    responses = [
        await _login(client, email="nobody@example.com"),
        await _login(client, email="ana@example.com", password=WRONG_PASSWORD),
        await _login(client, email="nopass@example.com"),
        await _login(client, email="inactive@example.com"),
    ]

    expected = (
        401,
        {
            "type": "about:blank",
            "title": "Invalid credentials",
            "status": 401,
            "detail": "The email or password is incorrect.",
            "code": "INVALID_CREDENTIALS",
        },
    )
    assert [_comparable(response) for response in responses] == [expected] * 4
    assert all("set-cookie" not in response.headers for response in responses)


async def test_validation_errors_do_not_reveal_the_password_policy(
    client: httpx.AsyncClient,
) -> None:
    short = await _login(client, password=SHORT_PASSWORD)
    empty = await _login(client, password=EMPTY_PASSWORD)
    too_long = await _login(client, password=TOO_LONG_PASSWORD)

    assert short.status_code == 401
    assert empty.status_code == 422
    assert too_long.status_code == 422


async def test_the_sixth_login_per_ip_and_email_within_a_minute_is_rate_limited(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await _create_user(engine)

    attempts = [await _login(client, password=WRONG_PASSWORD) for _ in range(5)]
    limited = await _login(client, email="ANA@example.com")
    other_email = await _login(client, email="other@example.com")
    other_ip = await _login(client, headers={"CF-Connecting-IP": "203.0.113.8"})

    assert [response.status_code for response in attempts] == [401] * 5
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert limited.headers["content-type"] == "application/problem+json"
    assert other_email.status_code == 401
    assert other_ip.status_code == 200


async def test_one_ip_is_capped_at_twenty_logins_a_minute_across_emails(
    client: httpx.AsyncClient,
) -> None:
    attempts = [await _login(client, email=f"user{n}@example.com") for n in range(20)]
    limited = await _login(client, email="user20@example.com")
    other_ip = await _login(
        client, email="user20@example.com", headers={"CF-Connecting-IP": "203.0.113.8"}
    )

    assert [response.status_code for response in attempts] == [401] * 20
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert other_ip.status_code == 401


async def test_me_returns_the_profile_for_a_valid_access_token(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    access_token = (await _login(client)).json()["access_token"]

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user_id),
        "email": "ana@example.com",
        "display_name": "Ana",
        "preferred_currency": "ARS",
        "email_verified": True,
    }
    assert response.headers["cache-control"] == "no-store"


def _expired_token(app: FastAPI, user_id: uuid.UUID) -> str:
    token: str = app.state.access_tokens.issue(
        user_id, now=datetime.now(UTC) - timedelta(minutes=16)
    )[0]
    return token


@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param(None, id="missing"),
        pytest.param("Bearer garbage", id="garbage"),
        pytest.param("Basic YW5hOnBhc3M=", id="another scheme"),
        pytest.param("expired", id="expired"),
    ],
)
async def test_me_rejects_a_request_without_a_valid_access_token(
    client: httpx.AsyncClient, engine: AsyncEngine, app: FastAPI, authorization: str | None
) -> None:
    user_id = await _create_user(engine)
    if authorization == "expired":
        authorization = f"Bearer {_expired_token(app, user_id)}"
    headers = {"Authorization": authorization} if authorization else {}

    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_rejects_a_token_for_an_unknown_or_inactive_user(
    client: httpx.AsyncClient, engine: AsyncEngine, app: FastAPI
) -> None:
    inactive_id = await _create_user(engine, is_active=False)
    unknown_token, _ = app.state.access_tokens.issue(uuid.uuid4())
    inactive_token, _ = app.state.access_tokens.issue(inactive_id)

    responses = [
        await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        for token in (unknown_token, inactive_token)
    ]

    assert [response.status_code for response in responses] == [401, 401]
    assert all(response.headers["www-authenticate"] == "Bearer" for response in responses)
