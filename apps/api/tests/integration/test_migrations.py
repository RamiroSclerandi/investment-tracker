import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import enable_app_role_login

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]


def test_baseline_upgrades_and_downgrades(
    database_url: str, app_role_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(API_ROOT / "alembic.ini"))

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    # The session-scoped migrated database is shared with later tests.
    command.upgrade(config, "head")
    # Downgrading may drop the cluster-wide app role, so later tests need its login back.
    asyncio.run(enable_app_role_login(database_url, app_role_password))
