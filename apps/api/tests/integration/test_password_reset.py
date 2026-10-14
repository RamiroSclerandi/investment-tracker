import re
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import WEB_BASE_URL, RecordingEmailSender
from tests.integration.test_login import (
    CLIENT_IP,
    PASSWORD,
    _create_user,
    _login,
    _refresh_tokens,
)
from tests.integration.test_refresh import (
    _assert_cookie_cleared,
    _login_cookie,
    _refresh,
)

pytestmark = pytest.mark.integration

FORGOT_URL = "/api/v1/auth/password/forgot"
RESET_URL = "/api/v1/auth/password/reset"
NEW_PASSWORD = "a brand new long password"
THIRD_PASSWORD = "yet another long password"
TOKEN_IN_LINK = re.compile(re.escape(WEB_BASE_URL) + r"/reset-password#token=([\w-]+)")


def _reset_token(message_text: str) -> str:
    match = TOKEN_IN_LINK.search(message_text)
    assert match is not None
    return match[1]


async def _forgot(
    client: httpx.AsyncClient, email: str = "ana@example.com", ip: str = "203.0.113.20"
) -> httpx.Response:
    return await client.post(FORGOT_URL, json={"email": email}, headers={"CF-Connecting-IP": ip})


async def _reset(
    client: httpx.AsyncClient, token: str, password: str = NEW_PASSWORD, ip: str = "203.0.113.30"
) -> httpx.Response:
    return await client.post(
        RESET_URL,
        json={"token": token, "password": password},
        headers={"CF-Connecting-IP": ip},
    )


async def _request_reset_token(client: httpx.AsyncClient, emails: RecordingEmailSender) -> str:
    response = await _forgot(client)
    assert response.status_code == 202
    return _reset_token(emails.sent[-1].text)


async def _password_hash(engine: AsyncEngine, user_id: uuid.UUID) -> str | None:
    async with engine.connect() as connection:
        value: str | None = await connection.scalar(
            text("SELECT password_hash FROM app.users WHERE id = :id"), {"id": user_id}
        )
    return value


async def _reset_tokens(engine: AsyncEngine, user_id: uuid.UUID) -> list[dict[str, object]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT token_hash, used_at, extract(epoch FROM expires_at - created_at) AS ttl"
                " FROM app.email_tokens WHERE user_id = :id AND purpose = 'reset_password'"
                " ORDER BY created_at"
            ),
            {"id": user_id},
        )
        return [dict(row) for row in rows.mappings().all()]


@pytest.mark.parametrize("account", ["active", "unknown", "inactive", "unverified"])
async def test_forgot_answers_the_same_for_every_account_state(
    client: httpx.AsyncClient, engine: AsyncEngine, emails: RecordingEmailSender, account: str
) -> None:
    if account != "unknown":
        await _create_user(
            engine, is_active=account != "inactive", is_verified=account != "unverified"
        )

    response = await _forgot(client)

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    expected_recipients = [] if account in {"unknown", "inactive"} else ["ana@example.com"]
    assert [message.to for message in emails.sent] == expected_recipients


async def test_forgot_emails_a_reset_link_valid_for_30_minutes_stored_hashed(
    client: httpx.AsyncClient, engine: AsyncEngine, emails: RecordingEmailSender
) -> None:
    user_id = await _create_user(engine)

    token = await _request_reset_token(client, emails)

    [row] = await _reset_tokens(engine, user_id)
    assert row["token_hash"] != token
    assert row["used_at"] is None
    assert float(str(row["ttl"])) == pytest.approx(30 * 60, abs=5)
    assert emails.sent[0].subject == "Restablecé tu contraseña"


async def test_a_new_reset_link_invalidates_the_previous_one(
    client: httpx.AsyncClient, engine: AsyncEngine, emails: RecordingEmailSender
) -> None:
    user_id = await _create_user(engine)
    first = await _request_reset_token(client, emails)
    second = await _request_reset_token(client, emails)

    stale = await _reset(client, first)
    fresh = await _reset(client, second)

    assert stale.status_code == 400
    assert stale.json()["code"] == "INVALID_EMAIL_TOKEN"
    assert fresh.status_code == 204
    assert all(row["used_at"] is not None for row in await _reset_tokens(engine, user_id))


async def test_forgot_is_limited_to_three_per_minute_per_client_ip(
    client: httpx.AsyncClient,
) -> None:
    statuses = [(await _forgot(client, f"u{index}@example.com")).status_code for index in range(4)]
    other_ip = await _forgot(client, "other@example.com", ip="203.0.113.21")

    assert statuses == [202, 202, 202, 429]
    assert other_ip.status_code == 202


async def test_reset_changes_the_password_and_revokes_every_session(
    client: httpx.AsyncClient, engine: AsyncEngine, emails: RecordingEmailSender
) -> None:
    user_id = await _create_user(engine)
    first_cookie, _ = await _login_cookie(client)
    second_cookie, _ = await _login_cookie(client)
    token = await _request_reset_token(client, emails)

    response = await _reset(client, token)

    assert response.status_code == 204
    assert response.headers["cache-control"] == "no-store"
    _assert_cookie_cleared(response)
    assert all(row["revoked_at"] is not None for row in await _refresh_tokens(engine, user_id))
    assert (await _refresh(client, first_cookie)).status_code == 401
    assert (await _refresh(client, second_cookie)).status_code == 401
    assert (await _login(client)).status_code == 401
    assert (await _login(client, password=NEW_PASSWORD)).status_code == 200


async def test_a_reset_link_is_single_use(
    client: httpx.AsyncClient, engine: AsyncEngine, emails: RecordingEmailSender
) -> None:
    user_id = await _create_user(engine)
    token = await _request_reset_token(client, emails)
    await _reset(client, token)
    hash_after_first_use = await _password_hash(engine, user_id)

    again = await _reset(client, token, password=THIRD_PASSWORD)

    assert again.status_code == 400
    assert again.json()["code"] == "INVALID_EMAIL_TOKEN"
    assert await _password_hash(engine, user_id) == hash_after_first_use


@pytest.mark.parametrize("token_state", ["unknown", "expired", "verification"])
async def test_reset_rejects_a_bad_token_generically_without_changing_anything(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    emails: RecordingEmailSender,
    token_state: str,
) -> None:
    user_id = await _create_user(engine, is_verified=token_state != "verification")
    original_hash = await _password_hash(engine, user_id)
    cookie, _ = await _login_cookie(client) if token_state != "verification" else ("", "")
    token = "not-a-real-token"
    if token_state == "expired":
        token = await _request_reset_token(client, emails)
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE app.email_tokens SET expires_at = now() - interval '1 second'")
            )
    if token_state == "verification":
        await client.post("/api/v1/auth/resend-verification", json={"email": "ana@example.com"})
        token = emails.sent[-1].text.rsplit("#token=", 1)[1].split()[0]

    response = await _reset(client, token)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_EMAIL_TOKEN"
    assert response.json()["detail"] == "The link is invalid or has expired."
    assert await _password_hash(engine, user_id) == original_hash
    assert all(row["revoked_at"] is None for row in await _refresh_tokens(engine, user_id))
    if cookie:
        assert (await _refresh(client, cookie)).status_code == 200


async def test_reset_rejects_an_inactive_account(
    client: httpx.AsyncClient, engine: AsyncEngine, emails: RecordingEmailSender
) -> None:
    user_id = await _create_user(engine)
    token = await _request_reset_token(client, emails)
    original_hash = await _password_hash(engine, user_id)
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE app.users SET is_active = false"))

    response = await _reset(client, token)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_EMAIL_TOKEN"
    assert await _password_hash(engine, user_id) == original_hash


async def test_resetting_an_unverified_account_verifies_it(
    client: httpx.AsyncClient, engine: AsyncEngine, emails: RecordingEmailSender
) -> None:
    await _create_user(engine, password_hash=None, is_verified=False)
    token = await _request_reset_token(client, emails)

    response = await _reset(client, token)

    assert response.status_code == 204
    assert (await _login(client, password=NEW_PASSWORD)).status_code == 200


@pytest.mark.parametrize(("length", "expected"), [(11, 422), (12, 204), (128, 204), (129, 422)])
async def test_reset_enforces_the_password_length_bounds(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    emails: RecordingEmailSender,
    length: int,
    expected: int,
) -> None:
    await _create_user(engine)
    token = await _request_reset_token(client, emails)

    response = await _reset(client, token, password="x" * length)

    assert response.status_code == expected
    if expected == 422:
        assert any(error["loc"][-1] == "password" for error in response.json()["errors"])
        assert (await _login(client, password=PASSWORD)).status_code == 200


async def test_reset_is_limited_to_ten_per_minute_per_client_ip(
    client: httpx.AsyncClient,
) -> None:
    statuses = [(await _reset(client, "nope")).status_code for _ in range(11)]

    assert statuses == [400] * 10 + [429]


async def test_verify_email_still_works_alongside_reset_tokens(
    client: httpx.AsyncClient, engine: AsyncEngine, emails: RecordingEmailSender
) -> None:
    await _create_user(engine, is_verified=False)
    await _forgot(client)
    await client.post("/api/v1/auth/resend-verification", json={"email": "ana@example.com"})
    verify_token = emails.sent[-1].text.rsplit("#token=", 1)[1].split()[0]

    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": verify_token, "password": PASSWORD},
        headers=CLIENT_IP,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "verified"}
