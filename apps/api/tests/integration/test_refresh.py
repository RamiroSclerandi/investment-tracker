import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from investment_tracker.auth.tokens import hash_token
from tests.integration.test_login import (
    CLIENT_IP,
    ME_URL,
    _cookie_attributes,
    _create_user,
    _login,
    _refresh_tokens,
)

pytestmark = pytest.mark.integration

REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
LOGOUT_ALL_URL = "/api/v1/auth/logout-all"
CSRF = {"X-Requested-With": "investment-tracker"}
COOKIE_ATTRIBUTES = {"httponly", "secure", "samesite=strict", "path=/api/v1/auth"}


async def _login_cookie(client: httpx.AsyncClient) -> tuple[str, str]:
    response = await _login(client)
    assert response.status_code == 200
    _, value, _ = _cookie_attributes(response.headers["set-cookie"])
    return value, response.json()["access_token"]


def _cookie_header(value: str | None) -> dict[str, str]:
    return {"Cookie": f"it_rt={value}"} if value is not None else {}


async def _refresh(
    client: httpx.AsyncClient,
    cookie: str | None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request_headers = {**CLIENT_IP, **CSRF, **_cookie_header(cookie)}
    if headers is not None:
        request_headers = {**CLIENT_IP, **headers, **_cookie_header(cookie)}
    return await client.post(REFRESH_URL, headers=request_headers)


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _row(rows: list[dict[str, object]], raw: str) -> dict[str, object]:
    [row] = [row for row in rows if row["token_hash"] == hash_token(raw)]
    return row


def _assert_cookie_cleared(response: httpx.Response) -> None:
    name, value, attributes = _cookie_attributes(response.headers["set-cookie"])
    assert name == "it_rt"
    assert value in {"", '""'}
    assert "max-age=0" in attributes
    assert attributes >= COOKIE_ATTRIBUTES


async def test_refresh_rotates_the_token_within_the_same_family(
    client: httpx.AsyncClient, engine: AsyncEngine, app: FastAPI
) -> None:
    user_id = await _create_user(engine)
    old, _ = await _login_cookie(client)

    response = await _refresh(client, old, headers={**CSRF, "User-Agent": "Firefox/141"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 900
    assert app.state.access_tokens.decode(body["access_token"]) == user_id
    assert response.headers["cache-control"] == "no-store"
    name, new, attributes = _cookie_attributes(response.headers["set-cookie"])
    assert name == "it_rt"
    assert new != old
    assert attributes == {*COOKIE_ATTRIBUTES, "max-age=2592000"}
    rows = await _refresh_tokens(engine, user_id)
    old_row, new_row = _row(rows, old), _row(rows, new)
    assert old_row["rotated_at"] is not None
    assert old_row["revoked_at"] is None
    assert new_row["family_id"] == old_row["family_id"]
    assert new_row["rotated_at"] is None
    assert new_row["user_agent"] == "Firefox/141"
    assert new_row["ip"] == "203.0.113.7"
    assert new_row["expires_at"] > old_row["expires_at"]  # type: ignore[operator]
    assert (await _refresh(client, new)).status_code == 200


async def _rotate(client: httpx.AsyncClient, cookie: str) -> str:
    _, rotated, _ = _cookie_attributes((await _refresh(client, cookie)).headers["set-cookie"])
    return rotated


async def _age_rotation(engine: AsyncEngine, raw: str, seconds: int) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE app.refresh_tokens SET rotated_at = rotated_at - make_interval(secs => :s)"
                " WHERE token_hash = :token_hash"
            ),
            {"s": seconds, "token_hash": hash_token(raw)},
        )


async def test_retrying_a_rotation_whose_response_was_lost_issues_a_fresh_token(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    old, _ = await _login_cookie(client)
    lost = await _rotate(client, old)
    rotated_at = _row(await _refresh_tokens(engine, user_id), old)["rotated_at"]

    retry = await _refresh(client, old)

    assert retry.status_code == 200
    _, fresh, _ = _cookie_attributes(retry.headers["set-cookie"])
    rows = await _refresh_tokens(engine, user_id)
    assert _row(rows, old)["rotated_at"] == rotated_at
    assert _row(rows, lost)["revoked_at"] is not None
    assert _row(rows, fresh)["revoked_at"] is None
    assert (await _refresh(client, lost)).status_code == 401
    assert (await _refresh(client, fresh)).status_code == 200


async def test_reusing_a_rotated_token_after_the_grace_window_revokes_the_whole_family(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    old, _ = await _login_cookie(client)
    newest = await _rotate(client, old)
    await _age_rotation(engine, old, 31)

    reused = await _refresh(client, old)

    assert reused.status_code == 401
    assert (await _refresh(client, newest)).status_code == 401
    rows = await _refresh_tokens(engine, user_id)
    assert all(row["revoked_at"] is not None for row in rows)


async def test_reusing_a_rotated_token_revokes_the_whole_family(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    old, _ = await _login_cookie(client)
    used = await _rotate(client, old)
    newest = await _rotate(client, used)

    reused = await _refresh(client, old)
    after_reuse = await _refresh(client, newest)

    assert reused.status_code == 401
    assert reused.json()["code"] == "INVALID_REFRESH_TOKEN"
    _assert_cookie_cleared(reused)
    assert after_reuse.status_code == 401
    rows = await _refresh_tokens(engine, user_id)
    assert all(row["revoked_at"] is not None for row in rows)


async def test_reuse_leaves_other_families_alone(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await _create_user(engine)
    old, _ = await _login_cookie(client)
    other, _ = await _login_cookie(client)
    await _rotate(client, await _rotate(client, old))

    await _refresh(client, old)

    assert (await _refresh(client, other)).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="missing"),
        pytest.param({"X-Requested-With": "XMLHttpRequest"}, id="wrong"),
    ],
)
async def test_refresh_without_the_csrf_header_is_forbidden_and_rotates_nothing(
    client: httpx.AsyncClient, engine: AsyncEngine, headers: dict[str, str]
) -> None:
    user_id = await _create_user(engine)
    cookie, _ = await _login_cookie(client)

    response = await _refresh(client, cookie, headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_HEADER_REQUIRED"
    [row] = await _refresh_tokens(engine, user_id)
    assert row["rotated_at"] is None
    assert row["revoked_at"] is None


async def _expire_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE app.refresh_tokens SET expires_at = now() - interval '1 second'")
        )


async def _revoke_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE app.refresh_tokens SET revoked_at = now()"))


@pytest.mark.parametrize("case", ["missing", "garbage", "expired", "revoked"])
async def test_refresh_rejects_an_unusable_cookie_and_clears_it(
    client: httpx.AsyncClient, engine: AsyncEngine, case: str
) -> None:
    user_id = await _create_user(engine)
    cookie: str | None = None
    if case == "garbage":
        cookie = "garbage"
    elif case in {"expired", "revoked"}:
        cookie, _ = await _login_cookie(client)
        await (_expire_all(engine) if case == "expired" else _revoke_all(engine))

    response = await _refresh(client, cookie)

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_REFRESH_TOKEN"
    _assert_cookie_cleared(response)
    assert all(row["rotated_at"] is None for row in await _refresh_tokens(engine, user_id))


async def test_refresh_for_an_inactive_user_revokes_the_family(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    cookie, _ = await _login_cookie(client)
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE app.users SET is_active = false"))

    response = await _refresh(client, cookie)

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_REFRESH_TOKEN"
    [row] = await _refresh_tokens(engine, user_id)
    assert row["revoked_at"] is not None
    assert row["rotated_at"] is None


async def test_the_thirty_first_refresh_per_ip_within_a_minute_is_rate_limited(
    client: httpx.AsyncClient,
) -> None:
    attempts = [await _refresh(client, None) for _ in range(30)]
    limited = await _refresh(client, None)
    other_ip = await client.post(REFRESH_URL, headers={**CSRF, "CF-Connecting-IP": "203.0.113.8"})

    assert [response.status_code for response in attempts] == [401] * 30
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert other_ip.status_code == 401


async def test_concurrent_refreshes_with_the_same_token_leave_exactly_one_live_token(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    cookie, _ = await _login_cookie(client)

    responses = await asyncio.gather(_refresh(client, cookie), _refresh(client, cookie))

    assert [response.status_code for response in responses] == [200, 200]
    rows = await _refresh_tokens(engine, user_id)
    live = [row for row in rows if row["rotated_at"] is None and row["revoked_at"] is None]
    assert len(rows) == 3
    assert len(live) == 1


async def _logout(client: httpx.AsyncClient, cookie: str | None) -> httpx.Response:
    return await client.post(LOGOUT_URL, headers={**CSRF, **_cookie_header(cookie)})


async def test_logout_revokes_the_family_clears_the_cookie_and_is_idempotent(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    old, _ = await _login_cookie(client)
    _, newest, _ = _cookie_attributes((await _refresh(client, old)).headers["set-cookie"])
    other, _ = await _login_cookie(client)

    first = await _logout(client, newest)
    second = await _logout(client, newest)

    assert first.status_code == 204
    assert second.status_code == 204
    _assert_cookie_cleared(first)
    _assert_cookie_cleared(second)
    rows = await _refresh_tokens(engine, user_id)
    assert _row(rows, old)["revoked_at"] is not None
    assert _row(rows, newest)["revoked_at"] is not None
    assert _row(rows, other)["revoked_at"] is None
    assert (await _refresh(client, newest)).status_code == 401


@pytest.mark.parametrize("cookie", [None, "garbage"])
async def test_logout_without_a_known_cookie_still_succeeds(
    client: httpx.AsyncClient, cookie: str | None
) -> None:
    response = await _logout(client, cookie)

    assert response.status_code == 204
    _assert_cookie_cleared(response)


async def test_logout_without_the_csrf_header_is_forbidden(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    cookie, _ = await _login_cookie(client)

    response = await client.post(LOGOUT_URL, headers=_cookie_header(cookie))

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_HEADER_REQUIRED"
    [row] = await _refresh_tokens(engine, user_id)
    assert row["revoked_at"] is None


async def test_logout_all_revokes_every_family_of_the_user(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    other_user = await _create_user(engine, "bob@example.com")
    first, access_token = await _login_cookie(client)
    second, _ = await _login_cookie(client)
    bob = await _login(client, email="bob@example.com")
    assert bob.status_code == 200

    response = await client.post(LOGOUT_ALL_URL, headers=_bearer(access_token))

    assert response.status_code == 204
    _assert_cookie_cleared(response)
    assert all(row["revoked_at"] is not None for row in await _refresh_tokens(engine, user_id))
    assert (await _refresh(client, first)).status_code == 401
    assert (await _refresh(client, second)).status_code == 401
    [bob_row] = await _refresh_tokens(engine, other_user)
    assert bob_row["revoked_at"] is None


async def test_logout_all_requires_an_access_token(client: httpx.AsyncClient) -> None:
    response = await client.post(LOGOUT_ALL_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


async def test_patch_me_updates_the_display_name_and_then_the_currency(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    _, access_token = await _login_cookie(client)

    renamed = await client.patch(
        ME_URL, json={"display_name": "  Ana María  "}, headers=_bearer(access_token)
    )
    switched = await client.patch(
        ME_URL, json={"preferred_currency": "USD"}, headers=_bearer(access_token)
    )
    profile = await client.get(ME_URL, headers=_bearer(access_token))

    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Ana María"
    assert renamed.json()["preferred_currency"] == "ARS"
    assert renamed.headers["cache-control"] == "no-store"
    expected = {
        "id": str(user_id),
        "email": "ana@example.com",
        "display_name": "Ana María",
        "preferred_currency": "USD",
        "email_verified": True,
    }
    assert switched.status_code == 200
    assert switched.json() == expected
    assert profile.json() == expected


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty"),
        pytest.param({"display_name": None}, id="only null"),
        pytest.param({"display_name": "Ana\x07Maria"}, id="control character"),
        pytest.param({"display_name": "Ana" + chr(0x2028) + "Maria"}, id="line separator"),
        pytest.param({"display_name": "   "}, id="blank"),
        pytest.param({"display_name": "x" * 81}, id="too long"),
        pytest.param({"preferred_currency": "EUR"}, id="unknown currency"),
    ],
)
async def test_patch_me_rejects_an_invalid_body(
    client: httpx.AsyncClient, engine: AsyncEngine, body: dict[str, object]
) -> None:
    await _create_user(engine)
    _, access_token = await _login_cookie(client)

    response = await client.patch(ME_URL, json=body, headers=_bearer(access_token))

    assert response.status_code == 422
    async with engine.connect() as connection:
        name = await connection.scalar(text("SELECT display_name FROM app.users"))
    assert name == "Ana"


async def test_patch_me_requires_an_access_token(client: httpx.AsyncClient) -> None:
    response = await client.patch(ME_URL, json={"display_name": "Eve"})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


async def test_patch_me_rejects_a_token_for_an_unknown_user(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    token, _ = app.state.access_tokens.issue(uuid.uuid4())

    response = await client.patch(ME_URL, json={"display_name": "Eve"}, headers=_bearer(token))

    assert response.status_code == 401


async def _age_family(engine: AsyncEngine, days: int) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE app.refresh_tokens SET created_at = now() - make_interval(days => :days)"),
            {"days": days},
        )


async def test_a_refresh_after_the_absolute_session_lifetime_revokes_the_family(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    cookie, _ = await _login_cookie(client)
    await _age_family(engine, 61)

    response = await _refresh(client, cookie)

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_REFRESH_TOKEN"
    _assert_cookie_cleared(response)
    [row] = await _refresh_tokens(engine, user_id)
    assert row["revoked_at"] is not None
    assert row["rotated_at"] is None


async def test_rotation_never_extends_a_session_past_its_absolute_lifetime(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    old, _ = await _login_cookie(client)
    await _age_family(engine, 45)

    response = await _refresh(client, old)

    assert response.status_code == 200
    _, new, _ = _cookie_attributes(response.headers["set-cookie"])
    expires_at = _row(await _refresh_tokens(engine, user_id), new)["expires_at"]
    assert isinstance(expires_at, datetime)
    remaining = expires_at - datetime.now(UTC)
    assert timedelta(days=14, hours=23) < remaining <= timedelta(days=15)


@pytest.mark.parametrize("field", [{"email": "eve@example.com"}, {"is_active": False}])
async def test_patch_me_rejects_unknown_fields(
    client: httpx.AsyncClient, engine: AsyncEngine, field: dict[str, object]
) -> None:
    await _create_user(engine)
    _, access_token = await _login_cookie(client)

    response = await client.patch(
        ME_URL, json={"display_name": "Eve", **field}, headers=_bearer(access_token)
    )

    assert response.status_code == 422
    async with engine.connect() as connection:
        row = (
            await connection.execute(text("SELECT email, display_name, is_active FROM app.users"))
        ).one()
    assert tuple(row) == ("ana@example.com", "Ana", True)
