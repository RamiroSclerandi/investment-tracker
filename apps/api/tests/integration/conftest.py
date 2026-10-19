import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from investment_tracker.core.email import EmailMessage
from investment_tracker.core.rate_limit import forgot_email_limiter, limiter, login_limiter
from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app

POSTGRES_IMAGE = os.environ.get("TEST_POSTGRES_IMAGE", "postgres:17")
API_ROOT = Path(__file__).resolve().parents[2]
WEB_BASE_URL = "https://app.example.com"
APP_ROLE = "app_rw"
# Supabase creates these roles and can expose a schema to them; plain Postgres has neither.
SUPABASE_ROLES = "anon, authenticated, service_role"
LAST_REVISION_BEFORE_REVOKE = "0004"
CREATE_SUPABASE_ROLES = """
    DO $$
    DECLARE
        role_name text;
    BEGIN
        FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                EXECUTE format('CREATE ROLE %I NOLOGIN', role_name);
            END IF;
        END LOOP;
    END
    $$
"""
EXPOSE_APP_SCHEMA = (
    f"GRANT USAGE ON SCHEMA app TO {SUPABASE_ROLES}",
    f"GRANT ALL ON ALL TABLES IN SCHEMA app TO {SUPABASE_ROLES}",
    f"ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO {SUPABASE_ROLES}",
)


class RecordingEmailSender:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


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


async def enable_app_role_login(owner_url: str, password: str) -> None:
    # The password travels as a bound, hidden parameter so it never appears in statement text.
    owner = create_async_engine(owner_url, hide_parameters=True)
    async with owner.begin() as connection:
        await connection.execute(
            text("SELECT set_config('test.app_role_password', :password, true)"),
            {"password": password},
        )
        await connection.execute(
            text(
                "DO $$ BEGIN EXECUTE format('ALTER ROLE app_rw WITH LOGIN PASSWORD %L',"
                " current_setting('test.app_role_password')); END $$"
            )
        )
    await owner.dispose()


async def run_as_owner(owner_url: str, *statements: str) -> None:
    owner = create_async_engine(owner_url)
    async with owner.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement))
    await owner.dispose()


async def current_revision(owner_url: str) -> str | None:
    owner = create_async_engine(owner_url)
    async with owner.connect() as connection:
        revision = None
        if await connection.scalar(text("SELECT to_regclass('public.alembic_version')")):
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    await owner.dispose()
    return revision


def app_role_url(owner_url: str, password: str) -> str:
    url = make_url(owner_url).set(username=APP_ROLE, password=password)
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def app_role_password() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture(scope="session")
def owner_database_url(database_url: str, alembic_config: Config) -> str:
    asyncio.run(run_as_owner(database_url, CREATE_SUPABASE_ROLES))
    revision = asyncio.run(current_revision(database_url))
    # Exposing the schema before the revoke migration proves the migration revokes it.
    if revision is None or revision <= LAST_REVISION_BEFORE_REVOKE:
        command.upgrade(alembic_config, LAST_REVISION_BEFORE_REVOKE)
        asyncio.run(run_as_owner(database_url, *EXPOSE_APP_SCHEMA))
    command.upgrade(alembic_config, "head")
    return database_url


# The app connects as the restricted role, so every integration test runs it under RLS.
@pytest.fixture(scope="session")
def migrated_database_url(owner_database_url: str, app_role_password: str) -> str:
    asyncio.run(enable_app_role_login(owner_database_url, app_role_password))
    return app_role_url(owner_database_url, app_role_password)


@pytest.fixture
async def engine(owner_database_url: str) -> AsyncIterator[AsyncEngine]:
    db_engine = create_async_engine(owner_database_url)
    async with db_engine.begin() as connection:
        await connection.execute(text("TRUNCATE app.users CASCADE"))
    yield db_engine
    await db_engine.dispose()


@pytest.fixture
def emails() -> RecordingEmailSender:
    return RecordingEmailSender()


@pytest.fixture
def app(migrated_database_url: str, emails: RecordingEmailSender) -> FastAPI:
    limiter.reset()
    login_limiter.reset()
    forgot_email_limiter.reset()
    settings = Settings(
        database_url=SecretStr(migrated_database_url),
        web_base_url=WEB_BASE_URL,
        _env_file=None,
    )
    return create_app(settings, email_sender=emails)


@pytest.fixture
async def client(app: FastAPI, engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as http_client,
    ):
        yield http_client
