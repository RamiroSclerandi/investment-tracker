import httpx
from fastapi import FastAPI

from investment_tracker.core.errors import DomainError


class InsufficientHoldingError(DomainError):
    code = "INSUFFICIENT_HOLDING"
    status = 409
    title = "Insufficient holding"


async def test_unknown_exception_returns_generic_problem(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    response = await client.get("/boom")

    body = response.json()
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert body["code"] == "INTERNAL_ERROR"
    assert body["status"] == 500
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text


async def test_domain_error_maps_to_problem(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/domain")
    async def domain() -> None:
        raise InsufficientHoldingError("Cannot sell 5 units, only 2 held")

    response = await client.get("/domain")

    body = response.json()
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert body["code"] == "INSUFFICIENT_HOLDING"
    assert body["title"] == "Insufficient holding"
    assert body["detail"] == "Cannot sell 5 units, only 2 held"
    assert body["request_id"] == response.headers["X-Request-ID"]


async def test_unknown_route_maps_to_problem(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/missing")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "HTTP_404"


async def test_validation_error_maps_to_problem(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/items/{item_id}")
    async def get_item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    response = await client.get("/items/not-a-number")

    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert body["code"] == "VALIDATION_ERROR"
    assert body["request_id"] == response.headers["X-Request-ID"]
