from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SMTP_SCHEMES = frozenset({"smtp", "smtp+starttls", "smtps"})
TLS_SMTP_SCHEMES = frozenset({"smtp+starttls", "smtps"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    readyz_timeout_seconds: float = Field(default=2.0, gt=0)
    smtp_url: SecretStr | None = None
    email_from: str = "Investment Tracker <no-reply@investment-tracker.local>"
    web_base_url: str = "http://localhost:5173"

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
