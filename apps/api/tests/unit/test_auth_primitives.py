import hashlib

from investment_tracker.auth.emails import verification_email
from investment_tracker.auth.passwords import hash_password
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
