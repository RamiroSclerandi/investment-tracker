from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import cast

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from investment_tracker.auth.repository import UserRepository
from investment_tracker.core.db import get_session
from investment_tracker.core.email import EmailMessage
from investment_tracker.core.rate_limit import limiter
from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app

DATABASE_URL = SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test")
REGISTER_URL = "/api/v1/auth/register"
BODY = {"email": "ana@example.com", "password": "correct horse battery", "display_name": "Ana"}


class RecordingEmailSender:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


@asynccontextmanager
async def _no_transaction() -> AsyncIterator[None]:
    yield


class BareSession:
    # Only begin() is reached: the fake repository below raises before any statement runs.
    def begin(self) -> AbstractAsyncContextManager[None]:
        return _no_transaction()


async def test_a_registration_losing_a_concurrency_race_still_answers_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter.reset()
    emails = RecordingEmailSender()
    app = create_app(
        Settings(
            database_url=DATABASE_URL,
            web_base_url="https://app.example.com",
            _env_file=None,
        ),
        email_sender=emails,
    )

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, BareSession())

    async def no_user(repository: UserRepository, email: str) -> None:
        return None

    async def lose_the_race(repository: UserRepository, user: object) -> None:
        raise IntegrityError("INSERT INTO app.users", None, RuntimeError("duplicate key"))

    monkeypatch.setattr(UserRepository, "get_by_email_for_update", no_user)
    monkeypatch.setattr(UserRepository, "add", lose_the_race)
    app.dependency_overrides[get_session] = override_get_session

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(REGISTER_URL, json=BODY)

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert emails.sent == []
