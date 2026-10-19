import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.requests import Request

from investment_tracker.core.rate_limit import UNKNOWN_CLIENT_KEY, client_ip, client_ip_key
from investment_tracker.core.settings import Settings

PROXY_SECRET = "s" * 40


def _request(headers: dict[str, str], proxy_secret: str | None = None) -> Request:
    app = FastAPI()
    app.state.settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test"),
        proxy_shared_secret=SecretStr(proxy_secret) if proxy_secret else None,
        _env_file=None,
    )
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "headers": raw, "client": ("10.0.0.9", 1234), "app": app})


def test_key_is_the_cloudflare_connecting_ip() -> None:
    assert client_ip_key(_request({"CF-Connecting-IP": "203.0.113.7"})) == "203.0.113.7"


def test_ipv6_is_keyed_by_its_normalized_64_network() -> None:
    assert client_ip_key(_request({"CF-Connecting-IP": "2001:DB8::0:1"})) == "2001:db8::/64"


def test_ipv6_addresses_in_the_same_64_share_a_key() -> None:
    first = client_ip_key(_request({"CF-Connecting-IP": "2001:db8::1"}))
    second = client_ip_key(_request({"CF-Connecting-IP": "2001:db8::ffff:ffff:ffff:ffff"}))

    assert first == second


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"CF-Connecting-IP": "not-an-ip"},
        {"X-Forwarded-For": "198.51.100.1"},
        {"X-Real-IP": "198.51.100.1"},
        {"X-Vercel-Forwarded-For": "198.51.100.1"},
    ],
)
def test_requests_without_a_valid_cloudflare_ip_share_one_bucket(headers: dict[str, str]) -> None:
    assert client_ip_key(_request(headers)) == UNKNOWN_CLIENT_KEY


@pytest.mark.parametrize("address", ["fe80::1%eth0", "2001:db8::1%1"])
def test_a_scoped_ipv6_address_is_not_a_valid_client_ip(address: str) -> None:
    request = _request({"CF-Connecting-IP": address})

    assert client_ip(request) is None
    assert client_ip_key(request) == UNKNOWN_CLIENT_KEY


def test_a_verified_proxy_request_is_keyed_by_the_vercel_forwarded_ip() -> None:
    request = _request(
        {
            "CF-Connecting-IP": "203.0.113.7",
            "X-Proxy-Secret": PROXY_SECRET,
            "X-Vercel-Forwarded-For": " 198.51.100.4 , 10.0.0.1",
        },
        proxy_secret=PROXY_SECRET,
    )

    assert client_ip_key(request) == "198.51.100.4"


def test_a_verified_proxy_ipv6_client_is_keyed_by_its_64_network() -> None:
    request = _request(
        {"X-Proxy-Secret": PROXY_SECRET, "X-Vercel-Forwarded-For": "2001:db8::1"},
        proxy_secret=PROXY_SECRET,
    )

    assert client_ip_key(request) == "2001:db8::/64"


@pytest.mark.parametrize("forwarded", ["", "not-an-ip", "fe80::1%eth0"])
def test_a_verified_proxy_request_without_a_valid_forwarded_ip_shares_one_bucket(
    forwarded: str,
) -> None:
    request = _request(
        {
            "CF-Connecting-IP": "203.0.113.7",
            "X-Proxy-Secret": PROXY_SECRET,
            "X-Vercel-Forwarded-For": forwarded,
        },
        proxy_secret=PROXY_SECRET,
    )

    assert client_ip_key(request) == UNKNOWN_CLIENT_KEY


@pytest.mark.parametrize("supplied", ["wrong-secret", PROXY_SECRET[:-1], PROXY_SECRET + "x", ""])
def test_a_wrong_proxy_secret_falls_back_to_the_cloudflare_ip(supplied: str) -> None:
    request = _request(
        {
            "CF-Connecting-IP": "203.0.113.7",
            "X-Proxy-Secret": supplied,
            "X-Vercel-Forwarded-For": "198.51.100.4",
        },
        proxy_secret=PROXY_SECRET,
    )

    assert client_ip_key(request) == "203.0.113.7"


def test_the_proxy_header_is_ignored_when_no_secret_is_configured() -> None:
    request = _request(
        {
            "CF-Connecting-IP": "203.0.113.7",
            "X-Proxy-Secret": PROXY_SECRET,
            "X-Vercel-Forwarded-For": "198.51.100.4",
        }
    )

    assert client_ip_key(request) == "203.0.113.7"


def test_a_forged_vercel_forwarded_ip_without_the_secret_is_ignored() -> None:
    request = _request(
        {"CF-Connecting-IP": "203.0.113.7", "X-Vercel-Forwarded-For": "198.51.100.4"},
        proxy_secret=PROXY_SECRET,
    )

    assert client_ip_key(request) == "203.0.113.7"
