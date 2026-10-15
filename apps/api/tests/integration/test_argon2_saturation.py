import asyncio

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from investment_tracker.auth import passwords
from tests.integration.test_login import CLIENT_IP, PASSWORD
from tests.integration.test_registration import _register_body

pytestmark = pytest.mark.integration

LOGIN_URL = "/api/v1/auth/login"
REGISTER_URL = "/api/v1/auth/register"
VERIFY_URL = "/api/v1/auth/verify-email"
EMAIL = "ana@example.com"


@pytest.fixture
def saturated_argon2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(passwords, "_argon2_slots", asyncio.Semaphore(0))
    monkeypatch.setattr(passwords, "ARGON2_WAIT_SECONDS", 0.01)


def _assert_service_busy(response: httpx.Response) -> None:
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_BUSY"
    assert response.headers["retry-after"] == "5"


@pytest.mark.usefixtures("saturated_argon2")
async def test_login_answers_503_when_argon2_is_saturated(client: httpx.AsyncClient) -> None:
    response = await client.post(
        LOGIN_URL,
        json={"email": EMAIL, "password": PASSWORD},
        headers=CLIENT_IP,
    )

    _assert_service_busy(response)


@pytest.mark.usefixtures("saturated_argon2")
async def test_register_answers_503_when_argon2_is_saturated(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await client.post(
        REGISTER_URL,
        json=_register_body(),
        headers=CLIENT_IP,
    )

    _assert_service_busy(response)
    async with engine.connect() as connection:
        user_count: int = await connection.scalar(
            text("SELECT count(*) FROM app.users WHERE email = :email"), {"email": EMAIL}
        )
    assert user_count == 0


@pytest.mark.usefixtures("saturated_argon2")
async def test_verify_email_answers_503_when_argon2_is_saturated(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        VERIFY_URL,
        json={"token": "not-a-real-token", "password": PASSWORD},
        headers=CLIENT_IP,
    )

    _assert_service_busy(response)
