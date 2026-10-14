import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def test_every_table_in_the_app_schema_has_row_level_security(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT relname, relrowsecurity FROM pg_class"
                " WHERE relnamespace = 'app'::regnamespace AND relkind = 'r'"
            )
        )
        tables: dict[str, bool] = dict(rows.tuples().all())

    assert {"users", "email_tokens", "refresh_tokens"} <= tables.keys()
    assert [name for name, enabled in tables.items() if not enabled] == []
