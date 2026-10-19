import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

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


async def _run_as_owner(database_url: str, *statements: str) -> list[object]:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        results = []
        for statement in statements:
            result = await connection.execute(text(statement))
            results.append(result.scalar() if result.returns_rows else None)
    await engine.dispose()
    return results


def test_upgrade_refuses_a_pre_existing_app_role_with_unsafe_attributes(
    database_url: str, app_role_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(API_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    command.downgrade(config, "0004")
    asyncio.run(
        _run_as_owner(
            database_url,
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN"
            " ALTER ROLE app_rw BYPASSRLS;"
            " ELSE CREATE ROLE app_rw BYPASSRLS; END IF; END $$",
        )
    )

    with pytest.raises(DBAPIError, match="app_rw"):
        command.upgrade(config, "head")

    asyncio.run(
        _run_as_owner(database_url, "ALTER ROLE app_rw NOBYPASSRLS NOCREATEDB NOCREATEROLE")
    )
    command.upgrade(config, "head")
    asyncio.run(enable_app_role_login(database_url, app_role_password))
    [global_function_defaults] = asyncio.run(
        _run_as_owner(
            database_url,
            "SELECT count(*) FROM pg_default_acl WHERE defaclnamespace = 0"
            " AND defaclobjtype = 'f' AND defaclrole = current_user::regrole",
        )
    )
    # A global default would change every future owner function in every schema.
    assert global_function_defaults == 0


def test_upgrade_strips_default_grants_from_exposed_roles_on_new_market_tables(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(API_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    command.downgrade(config, "0005")
    grant_defaults = (
        "ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER"
        " GRANT ALL ON TABLES TO PUBLIC, anon, authenticated, service_role"
    )
    asyncio.run(_run_as_owner(database_url, grant_defaults))

    try:
        command.upgrade(config, "head")
        [exposed_grants] = asyncio.run(
            _run_as_owner(
                database_url,
                "SELECT count(*) FROM pg_class c, aclexplode(c.relacl) acl"
                " WHERE c.relnamespace = 'app'::regnamespace AND c.relname = 'assets'"
                " AND (acl.grantee = 0 OR acl.grantee IN (SELECT oid FROM pg_roles"
                " WHERE rolname IN ('anon', 'authenticated', 'service_role')))",
            )
        )
    finally:
        asyncio.run(
            _run_as_owner(
                database_url,
                "ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER"
                " REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated, service_role",
            )
        )

    assert exposed_grants == 0
