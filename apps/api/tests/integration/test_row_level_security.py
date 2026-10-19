import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from investment_tracker.auth.dependencies import CurrentUserDep
from investment_tracker.core.db import SessionDep

pytestmark = pytest.mark.integration

AUTH_TABLES = ("users", "email_tokens", "refresh_tokens", "oauth_accounts")
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
EXPECTED_PRIVILEGES = {
    "users": {"SELECT", "INSERT", "UPDATE"},
    "email_tokens": {"SELECT", "INSERT", "UPDATE"},
    "refresh_tokens": {"SELECT", "INSERT", "UPDATE"},
    "oauth_accounts": {"SELECT", "INSERT"},
}
EXPOSED_ROLES = ("anon", "authenticated", "service_role")
USER_ID_SETTING = text("SELECT current_setting('app.user_id', true)")


@pytest.fixture
async def app_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    db_engine = create_async_engine(migrated_database_url)
    yield db_engine
    await db_engine.dispose()


async def _scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as connection:
        return await connection.scalar(text(sql), params)


async def test_every_table_in_the_app_schema_has_row_level_security(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT relname, relrowsecurity FROM pg_class"
                " WHERE relnamespace = 'app'::regnamespace AND relkind = 'r'"
            )
        )
        tables: dict[str, bool] = dict(rows.tuples().all())

    assert set(AUTH_TABLES) <= tables.keys()
    assert [name for name, enabled in tables.items() if not enabled] == []


async def test_the_app_connects_as_a_non_owner_role_that_cannot_bypass_rls(
    engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with engine.connect() as connection:
        role = (
            await connection.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'app_rw'")
            )
        ).one()
        owned = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_class WHERE relnamespace = 'app'::regnamespace"
                " AND relowner = 'app_rw'::regrole"
            )
        )

    assert await _scalar(app_engine, "SELECT current_user") == "app_rw"
    assert role.rolsuper is False
    assert role.rolbypassrls is False
    assert owned == 0


async def test_app_rw_holds_only_the_table_privileges_the_code_uses(engine: AsyncEngine) -> None:
    granted: dict[str, set[str]] = {}
    for table in AUTH_TABLES:
        granted[table] = {
            privilege
            for privilege in TABLE_PRIVILEGES
            if await _scalar(
                engine,
                "SELECT has_table_privilege('app_rw', :table, :privilege)",
                table=f"app.{table}",
                privilege=privilege,
            )
        }

    assert granted == EXPECTED_PRIVILEGES


async def test_each_granted_operation_has_one_policy_for_app_rw_only(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT tablename, cmd, roles::text[] AS roles FROM pg_policies"
                " WHERE schemaname = 'app'"
            )
        )
        policies = rows.all()

    by_table: dict[str, list[str]] = {}
    for policy in policies:
        assert policy.roles == ["app_rw"]
        by_table.setdefault(policy.tablename, []).append(policy.cmd)
    assert {table: set(cmds) for table, cmds in by_table.items()} == EXPECTED_PRIVILEGES
    assert all(len(cmds) == len(set(cmds)) for cmds in by_table.values())


async def test_exposed_supabase_roles_and_public_have_no_access_to_the_app_schema(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as connection:
        grantees = set(
            (
                await connection.execute(
                    text(
                        "SELECT DISTINCT acl.grantee FROM pg_class c, aclexplode(c.relacl) acl"
                        " WHERE c.relnamespace = 'app'::regnamespace"
                        " UNION SELECT DISTINCT acl.grantee FROM pg_namespace n,"
                        " aclexplode(n.nspacl) acl WHERE n.nspname = 'app'"
                    )
                )
            ).scalars()
        )
        exposed = (
            await connection.execute(
                text("SELECT oid FROM pg_roles WHERE rolname = ANY(:names)"),
                {"names": list(EXPOSED_ROLES)},
            )
        ).scalars()
        exposed_oids = set(exposed)
        default_grantees = set(
            (
                await connection.execute(
                    text(
                        "SELECT DISTINCT acl.grantee FROM pg_default_acl d,"
                        " aclexplode(d.defaclacl) acl"
                        " WHERE d.defaclnamespace = 'app'::regnamespace"
                    )
                )
            ).scalars()
        )

        assert len(exposed_oids) == len(EXPOSED_ROLES)
        assert exposed_oids.isdisjoint(grantees)
        assert exposed_oids.isdisjoint(default_grantees)
        for oid in exposed_oids:
            usage = await connection.scalar(
                text("SELECT has_schema_privilege(CAST(:role AS oid), 'app', 'USAGE')"),
                {"role": oid},
            )
            assert usage is False
    public_oid = 0
    assert public_oid not in grantees


@pytest.mark.parametrize("table", AUTH_TABLES)
async def test_app_rw_cannot_delete_rows(app_engine: AsyncEngine, table: str) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with app_engine.begin() as connection:
            await connection.execute(text(f"DELETE FROM app.{table}"))  # noqa: S608


@pytest.fixture
async def table_without_policy(engine: AsyncEngine) -> AsyncIterator[str]:
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE app.rls_probe (id int)"))
        await connection.execute(text("ALTER TABLE app.rls_probe ENABLE ROW LEVEL SECURITY"))
        await connection.execute(text("GRANT SELECT ON app.rls_probe TO app_rw"))
        await connection.execute(text("INSERT INTO app.rls_probe VALUES (1)"))
    yield "app.rls_probe"
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE app.rls_probe"))


async def test_a_table_without_a_policy_returns_no_rows_to_app_rw(
    engine: AsyncEngine, app_engine: AsyncEngine, table_without_policy: str
) -> None:
    query = f"SELECT count(*) FROM {table_without_policy}"  # noqa: S608

    assert await _scalar(engine, query) == 1
    assert await _scalar(app_engine, query) == 0


async def test_the_user_id_setting_is_local_to_its_transaction(app_engine: AsyncEngine) -> None:
    user_id = str(uuid.uuid4())

    async with app_engine.connect() as connection:
        async with connection.begin():
            await connection.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": user_id}
            )
            inside = await connection.scalar(USER_ID_SETTING)
        after = await connection.scalar(USER_ID_SETTING)

    assert inside == user_id
    # Postgres reports a placeholder setting that was only ever set locally as empty, not NULL.
    assert after in {None, ""}


@pytest.fixture
def probed_app(app: FastAPI) -> FastAPI:
    async def read_setting(session: SessionDep) -> str | None:
        async with session.begin():
            value: str | None = await session.scalar(USER_ID_SETTING)
        return value

    async def authenticated(_user: CurrentUserDep, session: SessionDep) -> dict[str, str | None]:
        return {"user_id": await read_setting(session)}

    async def anonymous(session: SessionDep) -> dict[str, str | None]:
        return {"user_id": await read_setting(session)}

    app.add_api_route("/probe/authenticated", authenticated)
    app.add_api_route("/probe/anonymous", anonymous)
    return app


async def _create_user(engine: AsyncEngine) -> uuid.UUID:
    async with engine.begin() as connection:
        user_id: uuid.UUID = await connection.scalar(
            text(
                "INSERT INTO app.users (email, display_name, email_verified_at)"
                " VALUES ('rls@example.com', 'Rls', now()) RETURNING id"
            )
        )
    return user_id


async def test_an_authenticated_request_sets_its_user_id_for_later_transactions(
    probed_app: FastAPI, client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await _create_user(engine)
    token, _ = probed_app.state.access_tokens.issue(user_id)

    response = await client.get(
        "/probe/authenticated", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == httpx.codes.OK
    assert response.json() == {"user_id": str(user_id)}


async def test_an_unauthenticated_request_sets_no_user_id(
    probed_app: FastAPI, client: httpx.AsyncClient
) -> None:
    response = await client.get("/probe/anonymous")

    assert response.status_code == httpx.codes.OK
    assert response.json()["user_id"] in {None, ""}
