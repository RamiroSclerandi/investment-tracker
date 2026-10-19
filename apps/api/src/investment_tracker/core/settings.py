from typing import Literal, Self
from urllib.parse import urlsplit

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SMTP_SCHEMES = frozenset({"smtp", "smtp+starttls", "smtps"})
TLS_SMTP_SCHEMES = frozenset({"smtp+starttls", "smtps"})


def load_jwt_private_key(pem: SecretStr) -> Ed25519PrivateKey:
    error = ValueError("JWT_PRIVATE_KEY must be an Ed25519 private key in unencrypted PEM format.")
    try:
        key = load_pem_private_key(pem.get_secret_value().encode(), password=None)
    except ValueError, TypeError, UnsupportedAlgorithm:
        raise error from None
    if not isinstance(key, Ed25519PrivateKey):
        raise error
    return key


class Settings(BaseSettings):
    # Validation errors would otherwise echo raw env values, secrets included, into boot logs.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr
    environment: Literal["development", "test", "production"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    readyz_timeout_seconds: float = Field(default=2.0, gt=0)
    smtp_url: SecretStr | None = None
    email_from: str = "Investment Tracker <no-reply@investment-tracker.local>"
    web_base_url: str = "http://localhost:5173"
    jwt_private_key: SecretStr | None = None
    jwt_issuer: str = "investment-tracker"
    jwt_audience: str = "investment-tracker-web"
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    gmail_client_id: str | None = None
    gmail_client_secret: SecretStr | None = None
    gmail_refresh_token: SecretStr | None = None
    gmail_sender: EmailStr | None = None
    proxy_shared_secret: SecretStr | None = Field(default=None, min_length=32)

    @field_validator(
        "gmail_client_id",
        "gmail_client_secret",
        "gmail_refresh_token",
        "gmail_sender",
        mode="before",
    )
    @classmethod
    def treat_blank_gmail_values_as_unset(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(raw, str) and not raw.strip():
            return None
        return value

    @field_validator("web_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_smtp_url(self) -> Self:
        if self.smtp_url is None:
            return self
        scheme = urlsplit(self.smtp_url.get_secret_value()).scheme
        if scheme not in SMTP_SCHEMES:
            raise ValueError(f"SMTP_URL scheme must be one of {sorted(SMTP_SCHEMES)}.")
        if self.environment == "production" and scheme not in TLS_SMTP_SCHEMES:
            raise ValueError("SMTP_URL must use TLS in production (smtp+starttls:// or smtps://).")
        return self

    @model_validator(mode="after")
    def validate_gmail_config(self) -> Self:
        values = {
            "GMAIL_CLIENT_ID": self.gmail_client_id,
            "GMAIL_CLIENT_SECRET": self.gmail_client_secret,
            "GMAIL_REFRESH_TOKEN": self.gmail_refresh_token,
            "GMAIL_SENDER": self.gmail_sender,
        }
        missing = [key for key, value in values.items() if value is None]
        if 0 < len(missing) < len(values):
            raise ValueError(
                f"Gmail API email needs all of {', '.join(values)} or none of them;"
                f" missing {', '.join(missing)}."
            )
        return self

    @model_validator(mode="after")
    def validate_jwt_private_key(self) -> Self:
        if self.jwt_private_key is not None:
            load_jwt_private_key(self.jwt_private_key)
        elif self.environment == "production":
            raise ValueError(
                "JWT_PRIVATE_KEY is required in production: set it to an Ed25519 private key"
                " in PEM format."
            )
        return self

    @model_validator(mode="after")
    def validate_production_email_sender(self) -> Self:
        if self.environment != "production":
            return self
        if self.gmail_sender is None and self.smtp_url is None:
            raise ValueError(
                "Production requires an email sender: set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET,"
                " GMAIL_REFRESH_TOKEN and GMAIL_SENDER, or a TLS SMTP_URL."
            )
        return self

    @model_validator(mode="after")
    def validate_production_web_base_url(self) -> Self:
        if self.environment != "production":
            return self
        parts = urlsplit(self.web_base_url)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError(
                "WEB_BASE_URL must be the public https origin of the web app in production,"
                " e.g. https://example.vercel.app."
            )
        return self

    @model_validator(mode="after")
    def validate_production_proxy_shared_secret(self) -> Self:
        if self.environment == "production" and self.proxy_shared_secret is None:
            raise ValueError(
                "PROXY_SHARED_SECRET is required in production: set it to the secret of at least"
                " 32 characters that the web proxy sends in the x-proxy-secret header."
            )
        return self
