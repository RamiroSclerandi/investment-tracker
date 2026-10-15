import base64
import json
import secrets
from collections.abc import Callable
from email import message_from_bytes, policy
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from investment_tracker.core.email import EmailDeliveryError, EmailMessage
from investment_tracker.core.gmail import GmailApiEmailSender

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
MESSAGE = EmailMessage(to="ana@example.com", subject="Verify your email", text="Hello Ana")
Handler = Callable[[httpx.Request], httpx.Response]


class FakeGoogle:
    def __init__(
        self, *, token_response: Handler | None = None, send_statuses: list[int] | None = None
    ) -> None:
        self.token_requests: list[httpx.Request] = []
        self.send_requests: list[httpx.Request] = []
        self.issued_tokens: list[str] = []
        self._token_response = token_response or self._issue_token
        self._send_statuses = send_statuses or []

    def _issue_token(self, request: httpx.Request) -> httpx.Response:
        token = f"access-{secrets.token_hex(8)}"
        self.issued_tokens.append(token)
        return httpx.Response(200, json={"access_token": token, "expires_in": 3600})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            self.token_requests.append(request)
            return self._token_response(request)
        if str(request.url) == SEND_URL:
            self.send_requests.append(request)
            status = self._send_statuses.pop(0) if self._send_statuses else 200
            return httpx.Response(status, json={"id": "sent"})
        return httpx.Response(404)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def credentials() -> tuple[str, SecretStr, SecretStr]:
    return (
        f"client-{secrets.token_hex(4)}",
        SecretStr(f"secret-{secrets.token_hex(8)}"),
        SecretStr(f"refresh-{secrets.token_hex(8)}"),
    )


def build_sender(
    handler: Handler, clock: Callable[[], float] | None = None
) -> tuple[GmailApiEmailSender, tuple[str, SecretStr, SecretStr]]:
    creds = credentials()
    sender = GmailApiEmailSender(
        *creds,
        sender="owner@gmail.com",
        display_name="Investment Tracker",
        transport=httpx.MockTransport(handler),
        clock=clock or FakeClock(),
    )
    return sender, creds


def bearer(request: httpx.Request) -> str:
    return request.headers["Authorization"].removeprefix("Bearer ")


async def test_the_token_refresh_posts_the_refresh_token_grant() -> None:
    google = FakeGoogle()
    sender, (client_id, client_secret, refresh_token) = build_sender(google.handler)

    await sender.send(MESSAGE)

    form = parse_qs(google.token_requests[0].content.decode())
    assert form == {
        "client_id": [client_id],
        "client_secret": [client_secret.get_secret_value()],
        "refresh_token": [refresh_token.get_secret_value()],
        "grant_type": ["refresh_token"],
    }


async def test_the_access_token_is_cached_across_sends() -> None:
    google = FakeGoogle()
    sender, _ = build_sender(google.handler)

    await sender.send(MESSAGE)
    await sender.send(MESSAGE)

    assert len(google.token_requests) == 1
    assert [bearer(r) for r in google.send_requests] == google.issued_tokens * 2


async def test_the_access_token_is_refreshed_a_minute_before_it_expires() -> None:
    google = FakeGoogle()
    clock = FakeClock()
    sender, _ = build_sender(google.handler, clock)

    await sender.send(MESSAGE)
    clock.now += 3600 - 61
    await sender.send(MESSAGE)
    clock.now += 1
    await sender.send(MESSAGE)

    assert len(google.token_requests) == 2
    assert [bearer(r) for r in google.send_requests] == [
        google.issued_tokens[0],
        google.issued_tokens[0],
        google.issued_tokens[1],
    ]


async def test_the_raw_message_carries_from_to_subject_and_body() -> None:
    google = FakeGoogle()
    sender, _ = build_sender(google.handler)

    await sender.send(MESSAGE)

    raw = json.loads(google.send_requests[0].content)["raw"]
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)
    assert parsed["From"] == "Investment Tracker <owner@gmail.com>"
    assert parsed["To"] == "ana@example.com"
    assert parsed["Subject"] == "Verify your email"
    assert parsed.get_content().strip() == "Hello Ana"


async def test_a_401_on_send_refreshes_once_and_retries_once() -> None:
    google = FakeGoogle(send_statuses=[401, 200])
    sender, _ = build_sender(google.handler)

    await sender.send(MESSAGE)

    assert len(google.token_requests) == 2
    assert [bearer(r) for r in google.send_requests] == google.issued_tokens


async def test_a_second_401_after_the_retry_fails_the_delivery() -> None:
    google = FakeGoogle(send_statuses=[401, 401])
    sender, _ = build_sender(google.handler)

    with pytest.raises(EmailDeliveryError, match=r"^gmail_send_failed: 401$"):
        await sender.send(MESSAGE)

    assert len(google.send_requests) == 2


async def test_an_invalid_grant_fails_without_leaking_credentials() -> None:
    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Token has been revoked."}
        )

    google = FakeGoogle(token_response=reject)
    sender, (client_id, client_secret, refresh_token) = build_sender(google.handler)

    with pytest.raises(EmailDeliveryError) as excinfo:
        await sender.send(MESSAGE)

    detail = str(excinfo.value)
    assert detail == "gmail_token_refresh_failed: invalid_grant"
    for leaked in (
        client_id,
        client_secret.get_secret_value(),
        refresh_token.get_secret_value(),
        MESSAGE.to,
    ):
        assert leaked not in detail
    assert google.send_requests == []


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(httpx.Response(200, content=b"not json"), id="malformed json"),
        pytest.param(httpx.Response(200, json={"expires_in": 3600}), id="missing access token"),
        pytest.param(httpx.Response(500, content=b"oops"), id="server error without json"),
    ],
)
async def test_an_unusable_token_response_fails_the_delivery(response: httpx.Response) -> None:
    google = FakeGoogle(token_response=lambda request: response)
    sender, _ = build_sender(google.handler)

    with pytest.raises(EmailDeliveryError, match=r"^gmail_token_refresh_failed: "):
        await sender.send(MESSAGE)


async def test_a_non_2xx_send_fails_with_the_status_only() -> None:
    google = FakeGoogle(send_statuses=[403])
    sender, _ = build_sender(google.handler)

    with pytest.raises(EmailDeliveryError) as excinfo:
        await sender.send(MESSAGE)

    assert str(excinfo.value) == "gmail_send_failed: 403"


async def test_a_network_error_fails_the_delivery() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    sender, _ = build_sender(unreachable)

    with pytest.raises(EmailDeliveryError) as excinfo:
        await sender.send(MESSAGE)

    assert str(excinfo.value) == "gmail_token_refresh_failed: ConnectError"
    assert excinfo.value.__cause__ is None
