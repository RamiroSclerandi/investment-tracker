from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app


@pytest.fixture
def app() -> FastAPI:
    settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test"),
    )
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
