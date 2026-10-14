import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

POSTGRES_IMAGE = os.environ.get("TEST_POSTGRES_IMAGE", "postgres:17")
API_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    configured = os.environ.get("DATABASE_URL")
    if configured:
        yield configured
        return
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Iterator[Config]:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    yield Config(str(API_ROOT / "alembic.ini"))
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous


@pytest.fixture(scope="session")
def migrated_database_url(database_url: str, alembic_config: Config) -> str:
    command.upgrade(alembic_config, "head")
    return database_url


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    db_engine = create_async_engine(migrated_database_url)
    async with db_engine.begin() as connection:
        await connection.execute(text("TRUNCATE app.users CASCADE"))
    yield db_engine
    await db_engine.dispose()
