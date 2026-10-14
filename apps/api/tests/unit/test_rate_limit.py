import pytest
from starlette.requests import Request

from investment_tracker.core.rate_limit import UNKNOWN_CLIENT_KEY, client_ip, client_ip_key


def _request(headers: dict[str, str]) -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "headers": raw, "client": ("10.0.0.9", 1234)})


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
