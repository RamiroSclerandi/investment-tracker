import hashlib

from investment_tracker.auth.emails import password_reset_email, verification_email
from investment_tracker.auth.passwords import (
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)
from investment_tracker.auth.tokens import hash_token, new_token


def test_passwords_are_hashed_with_argon2id() -> None:
    hashed = hash_password("correct horse battery")

    assert hashed.startswith("$argon2id$")
    assert "correct horse battery" not in hashed


def test_new_token_returns_the_raw_value_and_its_sha256() -> None:
    raw, token_hash = new_token()

    assert len(raw) >= 43
    assert token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert hash_token(raw) == token_hash


def test_new_tokens_are_unique() -> None:
    assert new_token()[0] != new_token()[0]


def test_verification_email_carries_the_token_in_the_link_fragment() -> None:
    message = verification_email(
        to="ana@example.com",
        display_name="Ana",
        web_base_url="https://app.example.com",
        raw_token="abc123",  # noqa: S106
    )

    assert message.to == "ana@example.com"
    assert message.subject == "Verificá tu email"
    assert "https://app.example.com/verify-email#token=abc123" in message.text
    assert "24 horas" in message.text


def test_password_reset_email_carries_the_token_in_the_link_fragment() -> None:
    message = password_reset_email(
        to="ana@example.com",
        display_name="Ana",
        web_base_url="https://app.example.com",
        raw_token="abc123",  # noqa: S106
    )

    assert message.to == "ana@example.com"
    assert message.subject == "Restablecé tu contraseña"
    assert "https://app.example.com/reset-password#token=abc123" in message.text
    assert "30 minutos" in message.text


def test_verify_password_accepts_the_matching_password() -> None:
    assert verify_password(hash_password("correct horse battery"), "correct horse battery")


def test_verify_password_rejects_a_different_password() -> None:
    assert not verify_password(hash_password("correct horse battery"), "wrong horse battery")


def test_verify_password_returns_false_for_a_garbage_hash() -> None:
    assert not verify_password("not-a-hash", "correct horse battery")


async def test_async_password_helpers_hash_and_verify_off_the_event_loop() -> None:
    hashed = await hash_password_async("correct horse battery")

    assert hashed.startswith("$argon2id$")
    assert await verify_password_async(hashed, "correct horse battery")
    assert not await verify_password_async(hashed, "wrong horse battery")
