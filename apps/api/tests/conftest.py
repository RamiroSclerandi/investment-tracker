import pytest


@pytest.fixture(autouse=True)
def environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
