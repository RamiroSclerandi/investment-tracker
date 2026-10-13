import httpx
import pytest
from pydantic import SecretStr

from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app

pytestmark = pytest.mark.integration


async def test_readyz_returns_ready_against_the_real_database(database_url: str) -> None:
    app = create_app(Settings(database_url=SecretStr(database_url)))
    transport = httpx.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        response = await client.get("/api/v1/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
