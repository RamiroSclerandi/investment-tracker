import os
from collections.abc import Iterator

import pytest
from testcontainers.community.postgres import PostgresContainer

POSTGRES_IMAGE = os.environ.get("TEST_POSTGRES_IMAGE", "postgres:17")


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    configured = os.environ.get("DATABASE_URL")
    if configured:
        yield configured
        return
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        yield container.get_connection_url()
