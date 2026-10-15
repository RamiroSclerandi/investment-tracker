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
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    environment: Literal["development", "test", "production"] = "development"
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
