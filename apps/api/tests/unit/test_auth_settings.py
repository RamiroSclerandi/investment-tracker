import pytest
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from pydantic import SecretStr, ValidationError

from investment_tracker.core.settings import Settings, load_jwt_private_key

DATABASE_URL = SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test")


def _ed25519_pem() -> str:
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


JWT_PRIVATE_KEY = SecretStr(_ed25519_pem())


def test_email_settings_default_to_unconfigured_delivery_and_local_web_url() -> None:
    settings = Settings(database_url=DATABASE_URL, _env_file=None)

    assert settings.smtp_url is None
    assert settings.web_base_url == "http://localhost:5173"


def test_production_rejects_plaintext_smtp() -> None:
    with pytest.raises(ValidationError, match="SMTP_URL must use TLS in production"):
        Settings(
            database_url=DATABASE_URL,
            environment="production",
            jwt_private_key=JWT_PRIVATE_KEY,
            smtp_url=SecretStr("smtp://user:pass@smtp.example.com:587"),
            _env_file=None,
        )


@pytest.mark.parametrize("scheme", ["smtp+starttls", "smtps"])
def test_production_accepts_tls_smtp(scheme: str) -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        environment="production",
        jwt_private_key=JWT_PRIVATE_KEY,
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


def test_jwt_settings_default_to_no_key_and_the_web_audience() -> None:
    settings = Settings(database_url=DATABASE_URL, _env_file=None)

    assert settings.jwt_private_key is None
    assert settings.jwt_issuer == "investment-tracker"
    assert settings.jwt_audience == "investment-tracker-web"


def test_production_requires_a_jwt_private_key() -> None:
    with pytest.raises(ValidationError, match="JWT_PRIVATE_KEY is required in production"):
        Settings(database_url=DATABASE_URL, environment="production", _env_file=None)


def test_production_accepts_an_ed25519_jwt_private_key() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        environment="production",
        jwt_private_key=JWT_PRIVATE_KEY,
        _env_file=None,
    )

    assert settings.jwt_private_key is not None
    assert isinstance(load_jwt_private_key(settings.jwt_private_key), Ed25519PrivateKey)


def _other_pems() -> list[object]:
    ec_key = generate_private_key(SECP256R1())
    ec_pem = ec_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    encrypted = Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(b"passphrase")
    )
    return [
        pytest.param("not a pem", id="garbage"),
        pytest.param(ec_pem, id="another key type"),
        pytest.param(encrypted.decode(), id="encrypted key"),
    ]


@pytest.mark.parametrize("environment", ["production", "development"])
@pytest.mark.parametrize("pem", _other_pems())
def test_a_jwt_private_key_that_is_not_an_ed25519_pem_is_rejected(
    environment: str, pem: str
) -> None:
    with pytest.raises(ValidationError, match="JWT_PRIVATE_KEY must be an Ed25519") as excinfo:
        Settings(
            database_url=DATABASE_URL,
            environment=environment,
            jwt_private_key=SecretStr(pem),
            _env_file=None,
        )

    assert pem not in str(excinfo.value)


def test_production_boots_without_google_credentials() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        environment="production",
        jwt_private_key=JWT_PRIVATE_KEY,
        _env_file=None,
    )

    assert settings.google_client_id is None
    assert settings.google_client_secret is None


def _gmail_settings() -> dict[str, object]:
    return {
        "gmail_client_id": "gmail-client",
        "gmail_client_secret": SecretStr("-".join(["gmail", "secret"])),
        "gmail_refresh_token": SecretStr("-".join(["gmail", "refresh"])),
        "gmail_sender": "owner@gmail.com",
    }


def test_gmail_settings_default_to_none() -> None:
    settings = Settings(database_url=DATABASE_URL, _env_file=None)

    assert settings.gmail_client_id is None
    assert settings.gmail_client_secret is None
    assert settings.gmail_refresh_token is None
    assert settings.gmail_sender is None


def test_a_complete_gmail_config_is_accepted() -> None:
    settings = Settings(database_url=DATABASE_URL, _env_file=None, **_gmail_settings())  # type: ignore[arg-type]

    assert settings.gmail_sender == "owner@gmail.com"


def test_a_partial_gmail_config_refuses_to_boot_naming_the_missing_keys() -> None:
    partial = _gmail_settings()
    del partial["gmail_refresh_token"], partial["gmail_sender"]

    with pytest.raises(
        ValidationError, match="missing GMAIL_REFRESH_TOKEN, GMAIL_SENDER"
    ) as excinfo:
        Settings(database_url=DATABASE_URL, _env_file=None, **partial)  # type: ignore[arg-type]

    assert "gmail-secret" not in str(excinfo.value)


def test_an_invalid_gmail_sender_is_rejected() -> None:
    config = _gmail_settings() | {"gmail_sender": "not-an-email"}

    with pytest.raises(ValidationError, match="gmail_sender"):
        Settings(database_url=DATABASE_URL, _env_file=None, **config)  # type: ignore[arg-type]
