import httpx
import pytest


async def test_valid_incoming_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/nope", headers={"X-Request-ID": "abc-123_DEF"})

    assert response.headers["X-Request-ID"] == "abc-123_DEF"


@pytest.mark.parametrize("value", ["x" * 200, "bad id with spaces", "a;b", ""])
async def test_invalid_incoming_request_id_is_replaced(
    client: httpx.AsyncClient, value: str
) -> None:
    response = await client.get("/nope", headers={"X-Request-ID": value})

    assert response.headers["X-Request-ID"] != value
    assert len(response.headers["X-Request-ID"]) == 36


async def test_newline_in_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    request = client.build_request("GET", "/nope")
    request.headers.raw.append((b"x-request-id", b"abc\ninjected"))

    response = await client.send(request)

    assert "\n" not in response.headers["X-Request-ID"]
    assert response.headers["X-Request-ID"] != "abc\ninjected"


async def test_missing_request_id_is_generated(client: httpx.AsyncClient) -> None:
    response = await client.get("/nope")

    assert len(response.headers["X-Request-ID"]) == 36
