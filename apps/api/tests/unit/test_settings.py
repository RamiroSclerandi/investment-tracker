import pytest
from pydantic import ValidationError

from investment_tracker.core.settings import Settings


def test_missing_database_url_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_database_url_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value().endswith("/test")
    assert "pass" not in repr(settings)
