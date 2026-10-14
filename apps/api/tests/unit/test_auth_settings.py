import pytest
from pydantic import SecretStr, ValidationError

from investment_tracker.core.settings import Settings

DATABASE_URL = SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test")


def test_email_settings_default_to_unconfigured_delivery_and_local_web_url() -> None:
    settings = Settings(database_url=DATABASE_URL, _env_file=None)

    assert settings.smtp_url is None
    assert settings.web_base_url == "http://localhost:5173"


def test_production_rejects_plaintext_smtp() -> None:
    with pytest.raises(ValidationError, match="SMTP_URL must use TLS in production"):
        Settings(
            database_url=DATABASE_URL,
            environment="production",
            smtp_url=SecretStr("smtp://user:pass@smtp.example.com:587"),
            _env_file=None,
        )


@pytest.mark.parametrize("scheme", ["smtp+starttls", "smtps"])
def test_production_accepts_tls_smtp(scheme: str) -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        environment="production",
        smtp_url=SecretStr(f"{scheme}://user:pass@smtp.example.com:587"),
        _env_file=None,
    )

    assert settings.smtp_url is not None


def test_unknown_smtp_scheme_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SMTP_URL scheme"):
        Settings(
            database_url=DATABASE_URL,
            smtp_url=SecretStr("http://smtp.example.com"),
            _env_file=None,
        )


def test_web_base_url_drops_the_trailing_slash() -> None:
    settings = Settings(
        database_url=DATABASE_URL, web_base_url="https://app.example.com/", _env_file=None
    )

    assert settings.web_base_url == "https://app.example.com"
