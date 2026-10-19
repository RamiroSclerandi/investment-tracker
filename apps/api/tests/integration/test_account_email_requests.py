import httpx
import pytest
import structlog
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tests.integration.conftest import RecordingEmailSender
from tests.integration.test_login import _create_user

pytestmark = pytest.mark.integration

FORGOT_URL = "/api/v1/auth/password/forgot"
RESEND_URL = "/api/v1/auth/resend-verification"
UNKNOWN_EMAIL = "nobody@example.com"
LEAKY_DETAIL = "connection to leaky-host.invalid as leaky-user failed"


class ResponseRecorder:
    def __init__(self, app: ASGIApp, events: list[str]) -> None:
        self._app = app
        self._events = events

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def recording_send(message: Message) -> None:
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                self._events.append("response")

        await self._app(scope, receive, recording_send)


class RecordingSessionmaker:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], events: list[str]) -> None:
        self._sessionmaker = sessionmaker
        self._events = events

    def __call__(self) -> AsyncSession:
        self._events.append("session")
        return self._sessionmaker()


class FailingSessionmaker:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def __call__(self) -> AsyncSession:
        raise self._error


async def _post_recording(
    app: FastAPI, url: str, email: str, ip: str
) -> tuple[httpx.Response, list[str]]:
    events: list[str] = []
    original = app.state.sessionmaker
    app.state.sessionmaker = RecordingSessionmaker(original, events)
    transport = httpx.ASGITransport(app=ResponseRecorder(app, events))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
            response = await http_client.post(
                url, json={"email": email}, headers={"CF-Connecting-IP": ip}
            )
    finally:
        app.state.sessionmaker = original
    return response, events


async def _active_tokens(engine: AsyncEngine, purpose: str) -> int:
    async with engine.connect() as connection:
        count: int = await connection.scalar(
            text(
                "SELECT count(*) FROM app.email_tokens WHERE purpose = :purpose AND used_at IS NULL"
            ),
            {"purpose": purpose},
        )
    return count


@pytest.mark.parametrize(
    ("url", "purpose", "is_verified"),
    [(FORGOT_URL, "reset_password", True), (RESEND_URL, "verify_email", False)],
)
async def test_the_account_work_runs_only_after_the_response_is_sent(
    app: FastAPI,
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    emails: RecordingEmailSender,
    url: str,
    purpose: str,
    is_verified: bool,
) -> None:
    await _create_user(engine, is_verified=is_verified)

    known, known_events = await _post_recording(app, url, "ana@example.com", "203.0.113.60")
    unknown, unknown_events = await _post_recording(app, url, UNKNOWN_EMAIL, "203.0.113.61")

    assert (known.status_code, known.json()) == (202, {"status": "accepted"})
    assert (unknown.status_code, unknown.json()) == (known.status_code, known.json())
    assert known_events == unknown_events == ["response", "session"]
    assert [message.to for message in emails.sent] == ["ana@example.com"]
    assert await _active_tokens(engine, purpose) == 1


@pytest.mark.parametrize("url", [FORGOT_URL, RESEND_URL])
@pytest.mark.parametrize(
    "error", [ConnectionRefusedError(LEAKY_DETAIL), ValueError(LEAKY_DETAIL)], ids=type
)
async def test_a_failure_after_the_response_is_logged_by_type_and_not_surfaced(
    app: FastAPI,
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    emails: RecordingEmailSender,
    url: str,
    error: Exception,
) -> None:
    await _create_user(engine, is_verified=False)
    app.state.sessionmaker = FailingSessionmaker(error)

    with structlog.testing.capture_logs() as logs:
        response = await client.post(
            url, json={"email": "ana@example.com"}, headers={"CF-Connecting-IP": "203.0.113.62"}
        )

    assert (response.status_code, response.json()) == (202, {"status": "accepted"})
    assert emails.sent == []
    failures = [entry for entry in logs if entry.get("event") == "account_email_task_failed"]
    assert failures == [
        {
            "event": "account_email_task_failed",
            "error_type": type(error).__name__,
            "log_level": "warning",
        }
    ]
    assert LEAKY_DETAIL not in str(logs)
