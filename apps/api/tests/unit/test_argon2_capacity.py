import asyncio

import httpx
import pytest
from fastapi import FastAPI

from investment_tracker.auth import passwords
from investment_tracker.auth.errors import PasswordHashingBusyError


@pytest.fixture
def saturated_argon2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(passwords, "_argon2_slots", asyncio.Semaphore(0))
    monkeypatch.setattr(passwords, "ARGON2_WAIT_SECONDS", 0.01)


@pytest.mark.usefixtures("saturated_argon2")
async def test_hashing_gives_up_when_no_argon2_slot_frees_in_time() -> None:
    with pytest.raises(PasswordHashingBusyError):
        await passwords.hash_password_async("correct horse battery")


@pytest.mark.usefixtures("saturated_argon2")
async def test_verifying_gives_up_when_no_argon2_slot_frees_in_time() -> None:
    with pytest.raises(PasswordHashingBusyError):
        await passwords.verify_password_async(passwords.DUMMY_PASSWORD_HASH, "x" * 12)


async def test_a_released_argon2_slot_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    slots = asyncio.Semaphore(1)
    monkeypatch.setattr(passwords, "_argon2_slots", slots)

    await passwords.hash_password_async("correct horse battery")
    await passwords.verify_password_async(passwords.DUMMY_PASSWORD_HASH, "x" * 12)

    assert not slots.locked()


@pytest.mark.usefixtures("saturated_argon2")
async def test_a_saturated_argon2_pool_answers_503_problem_json(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    @app.get("/hash")
    async def hash_route() -> None:
        await passwords.hash_password_async("correct horse battery")

    response = await client.get("/hash")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "SERVICE_BUSY"
