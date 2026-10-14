import re

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from investment_tracker.auth.passwords import verify_password
from investment_tracker.auth.service import AuthService
from investment_tracker.core.email import EmailMessage
from tests.integration.conftest import WEB_BASE_URL, RecordingEmailSender

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"
OTHER_PASSWORD = "another long password"
TOKEN_IN_LINK = re.compile(re.escape(WEB_BASE_URL) + r"/verify-email#token=([\w-]+)")


def _register_body(email: str = "ana@example.com", password: str = PASSWORD) -> dict[str, str]:
    return {"email": email, "password": password, "display_name": "Ana"}


def _token_from(message_text: str) -> str:
    match = TOKEN_IN_LINK.search(message_text)
    assert match is not None
    return match[1]


async def _user_row(engine: AsyncEngine, email: str) -> dict[str, object] | None:
    async with engine.connect() as connection:
        row = await connection.execute(
            text(
                "SELECT email::text AS email, password_hash, email_verified_at, display_name,"
                " preferred_currency::text AS preferred_currency FROM app.users WHERE email = :e"
            ),
            {"e": email},
        )
        found = row.mappings().first()
    return dict(found) if found is not None else None


async def test_register_creates_an_unverified_user_and_emails_a_verification_link(
    client: httpx.AsyncClient, emails: RecordingEmailSender, engine: AsyncEngine
) -> None:
    response = await client.post("/api/v1/auth/register", json=_register_body())

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    user = await _user_row(engine, "ana@example.com")
    assert user is not None
    assert user["email_verified_at"] is None
    assert user["display_name"] == "Ana"
    assert user["preferred_currency"] == "ARS"
    assert str(user["password_hash"]).startswith("$argon2id$")
    assert len(emails.sent) == 1
    assert emails.sent[0].to == "ana@example.com"
    _token_from(emails.sent[0].text)


async def test_verify_email_marks_the_user_verified_and_the_token_is_single_use(
    client: httpx.AsyncClient, emails: RecordingEmailSender, engine: AsyncEngine
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())
    token = _token_from(emails.sent[0].text)

    first = await client.post(
        "/api/v1/auth/verify-email", json={"token": token, "password": PASSWORD}
    )
    second = await client.post(
        "/api/v1/auth/verify-email", json={"token": token, "password": PASSWORD}
    )

    assert first.status_code == 200
    assert first.json() == {"status": "verified"}
    user = await _user_row(engine, "ana@example.com")
    assert user is not None
    assert user["email_verified_at"] is not None
    assert second.status_code == 400
    assert second.json()["code"] == "INVALID_EMAIL_TOKEN"


async def test_verify_email_rejects_an_expired_token(
    client: httpx.AsyncClient, emails: RecordingEmailSender, engine: AsyncEngine
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())
    token = _token_from(emails.sent[0].text)
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE app.email_tokens SET expires_at = now() - interval '1 second'")
        )

    response = await client.post(
        "/api/v1/auth/verify-email", json={"token": token, "password": PASSWORD}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_EMAIL_TOKEN"
    user = await _user_row(engine, "ana@example.com")
    assert user is not None
    assert user["email_verified_at"] is None


async def test_verify_email_rejects_an_unknown_token(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/verify-email", json={"token": "nope", "password": PASSWORD}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_EMAIL_TOKEN"


async def test_verify_email_with_the_registered_password_verifies(
    client: httpx.AsyncClient, emails: RecordingEmailSender, engine: AsyncEngine
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())

    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": _token_from(emails.sent[0].text), "password": PASSWORD},
    )

    assert response.status_code == 200
    user = await _user_row(engine, "ana@example.com")
    assert user is not None
    assert user["email_verified_at"] is not None


async def test_verify_email_with_a_wrong_password_fails_and_keeps_the_token_usable(
    client: httpx.AsyncClient, emails: RecordingEmailSender, engine: AsyncEngine
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())
    token = _token_from(emails.sent[0].text)

    wrong = await client.post(
        "/api/v1/auth/verify-email", json={"token": token, "password": OTHER_PASSWORD}
    )
    unverified = await _user_row(engine, "ana@example.com")
    right = await client.post(
        "/api/v1/auth/verify-email", json={"token": token, "password": PASSWORD}
    )

    assert wrong.status_code == 400
    assert wrong.json()["code"] == "INVALID_EMAIL_TOKEN"
    assert unverified is not None
    assert unverified["email_verified_at"] is None
    assert right.status_code == 200


async def test_verify_email_sets_the_password_of_an_account_without_one(
    client: httpx.AsyncClient, emails: RecordingEmailSender, engine: AsyncEngine
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())
    await client.post("/api/v1/auth/register", json=_register_body())

    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": _token_from(emails.sent[-1].text), "password": OTHER_PASSWORD},
    )

    assert response.status_code == 200
    user = await _user_row(engine, "ana@example.com")
    assert user is not None
    assert user["email_verified_at"] is not None
    stored_hash = str(user["password_hash"])
    assert stored_hash.startswith("$argon2id$")
    assert verify_password(stored_hash, OTHER_PASSWORD)


async def test_verify_email_rejects_an_inactive_user(
    client: httpx.AsyncClient, emails: RecordingEmailSender, engine: AsyncEngine
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE app.users SET is_active = false"))

    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": _token_from(emails.sent[0].text), "password": PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_EMAIL_TOKEN"
    user = await _user_row(engine, "ana@example.com")
    assert user is not None
    assert user["email_verified_at"] is None


async def test_a_reregistration_during_verification_invalidates_it(
    app: FastAPI,
    client: httpx.AsyncClient,
    emails: RecordingEmailSender,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())
    token = _token_from(emails.sent[0].text)
    original_proof = AuthService._prove_password
    reregistrations: list[EmailMessage | None] = []

    async def prove_then_reregister(
        service: AuthService, password_hash: str | None, password: str
    ) -> str | None:
        result = await original_proof(service, password_hash, password)
        async with app.state.sessionmaker() as session:
            other = AuthService(session, app.state.settings)
            reregistrations.append(
                await other.register("ana@example.com", OTHER_PASSWORD, "Mallory")
            )
        return result

    monkeypatch.setattr(AuthService, "_prove_password", prove_then_reregister)

    response = await client.post(
        "/api/v1/auth/verify-email", json={"token": token, "password": PASSWORD}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_EMAIL_TOKEN"
    user = await _user_row(engine, "ana@example.com")
    assert user is not None
    assert user["email_verified_at"] is None
    assert user["password_hash"] is None
    assert reregistrations[0] is not None


async def test_verify_email_is_limited_to_ten_per_minute_per_client_ip(
    client: httpx.AsyncClient,
) -> None:
    headers = {"CF-Connecting-IP": "203.0.113.9"}
    body = {"token": "nope", "password": PASSWORD}
    statuses = [
        (await client.post("/api/v1/auth/verify-email", json=body, headers=headers)).status_code
        for _ in range(11)
    ]

    assert statuses == [400] * 10 + [429]


async def test_verify_email_rejects_a_password_shorter_than_12(
    client: httpx.AsyncClient, emails: RecordingEmailSender
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())

    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": _token_from(emails.sent[0].text), "password": "x" * 11},
    )

    assert response.status_code == 422
    assert any(error["loc"][-1] == "password" for error in response.json()["errors"])


async def test_verification_tokens_expire_after_24_hours(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())

    async with engine.connect() as connection:
        lifetime = await connection.scalar(
            text("SELECT extract(epoch FROM expires_at - created_at) FROM app.email_tokens")
        )

    assert lifetime == pytest.approx(24 * 3600, abs=5)


async def test_registering_a_verified_email_answers_the_same_and_sends_nothing(
    client: httpx.AsyncClient, emails: RecordingEmailSender, engine: AsyncEngine
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())
    await client.post(
        "/api/v1/auth/verify-email",
        json={"token": _token_from(emails.sent[0].text), "password": PASSWORD},
    )
    before = await _user_row(engine, "ana@example.com")

    response = await client.post(
        "/api/v1/auth/register",
        json=_register_body(email="ANA@example.com", password=OTHER_PASSWORD),
    )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert len(emails.sent) == 1
    assert await _user_row(engine, "ana@example.com") == before


async def test_registering_an_unverified_email_again_replaces_the_pending_link(
    client: httpx.AsyncClient, emails: RecordingEmailSender
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())
    await client.post("/api/v1/auth/register", json=_register_body())
    old_token, new_token = (_token_from(message.text) for message in emails.sent)

    old = await client.post(
        "/api/v1/auth/verify-email", json={"token": old_token, "password": PASSWORD}
    )
    new = await client.post(
        "/api/v1/auth/verify-email", json={"token": new_token, "password": PASSWORD}
    )

    assert old.status_code == 400
    assert new.status_code == 200


async def test_registering_an_unverified_email_again_clears_the_password_and_keeps_the_name(
    client: httpx.AsyncClient, emails: RecordingEmailSender, engine: AsyncEngine
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())
    await client.post(
        "/api/v1/auth/register",
        json={"email": "ana@example.com", "password": OTHER_PASSWORD, "display_name": "Mallory"},
    )

    user = await _user_row(engine, "ana@example.com")
    verify = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": _token_from(emails.sent[-1].text), "password": PASSWORD},
    )

    assert user is not None
    assert user["password_hash"] is None
    assert user["display_name"] == "Ana"
    assert verify.status_code == 200


async def test_resend_verification_sends_a_fresh_link_to_unverified_users(
    client: httpx.AsyncClient, emails: RecordingEmailSender
) -> None:
    await client.post("/api/v1/auth/register", json=_register_body())

    response = await client.post(
        "/api/v1/auth/resend-verification", json={"email": "ana@example.com"}
    )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert len(emails.sent) == 2
    verify = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": _token_from(emails.sent[1].text), "password": PASSWORD},
    )
    assert verify.status_code == 200


@pytest.mark.parametrize("verified", [False, True])
async def test_resend_verification_does_not_reveal_unknown_or_verified_accounts(
    client: httpx.AsyncClient, emails: RecordingEmailSender, verified: bool
) -> None:
    if verified:
        await client.post("/api/v1/auth/register", json=_register_body())
        await client.post(
            "/api/v1/auth/verify-email",
            json={"token": _token_from(emails.sent[0].text), "password": PASSWORD},
        )
    sent_before = len(emails.sent)
    email = "ana@example.com" if verified else "ghost@example.com"

    response = await client.post("/api/v1/auth/resend-verification", json={"email": email})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert len(emails.sent) == sent_before


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (_register_body(password="x" * 11), "password"),
        (_register_body(password="x" * 129), "password"),
        (_register_body(email="not-an-email"), "email"),
        ({"email": "ana@example.com", "password": PASSWORD, "display_name": "  "}, "display_name"),
        (
            {
                "email": "ana@example.com",
                "password": PASSWORD,
                "display_name": "Ana\nVisit http://evil",
            },
            "display_name",
        ),
        (
            {
                "email": "ana@example.com",
                "password": PASSWORD,
                "display_name": "Ana\u2028Visit http://evil",
            },
            "display_name",
        ),
    ],
)
async def test_register_validates_its_fields(
    client: httpx.AsyncClient, engine: AsyncEngine, body: dict[str, str], field: str
) -> None:
    response = await client.post("/api/v1/auth/register", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert any(error["loc"][-1] == field for error in response.json()["errors"])
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM app.users")) == 0


async def test_password_length_bounds_are_inclusive(client: httpx.AsyncClient) -> None:
    shortest = await client.post(
        "/api/v1/auth/register", json=_register_body(email="a@example.com", password="x" * 12)
    )
    longest = await client.post(
        "/api/v1/auth/register", json=_register_body(email="b@example.com", password="x" * 128)
    )

    assert shortest.status_code == 202
    assert longest.status_code == 202


async def test_register_is_limited_to_three_per_minute_per_client_ip(
    client: httpx.AsyncClient,
) -> None:
    headers = {"CF-Connecting-IP": "203.0.113.7"}
    statuses = [
        (
            await client.post(
                "/api/v1/auth/register",
                json=_register_body(email=f"user{index}@example.com"),
                headers=headers,
            )
        ).status_code
        for index in range(4)
    ]
    other_ip = await client.post(
        "/api/v1/auth/register",
        json=_register_body(email="other@example.com"),
        headers={"CF-Connecting-IP": "203.0.113.8"},
    )

    assert statuses == [202, 202, 202, 429]
    assert other_ip.status_code == 202


async def test_rate_limited_responses_are_problem_json(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        await client.post("/api/v1/auth/resend-verification", json={"email": "a@example.com"})

    response = await client.post(
        "/api/v1/auth/resend-verification", json={"email": "a@example.com"}
    )

    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "RATE_LIMITED"


async def test_a_failed_email_delivery_still_answers_accepted(
    client: httpx.AsyncClient, emails: RecordingEmailSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    from investment_tracker.core.email import EmailDeliveryError

    async def fail(message: EmailMessage) -> None:
        raise EmailDeliveryError("SMTP delivery failed: ConnectionRefusedError")

    monkeypatch.setattr(emails, "send", fail)

    response = await client.post("/api/v1/auth/register", json=_register_body())

    assert response.status_code == 202
