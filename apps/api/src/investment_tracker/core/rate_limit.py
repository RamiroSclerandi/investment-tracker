import ipaddress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from investment_tracker.core.errors import problem_response

# Render's Cloudflare edge rejects forged values of this header; every other client-IP header
# can be forged on the direct-to-Render path.
CLIENT_IP_HEADER = "cf-connecting-ip"
UNKNOWN_CLIENT_KEY = "unknown-client"
IPV6_VERSION = 6


def client_ip_key(request: Request) -> str:
    try:
        address = ipaddress.ip_address(request.headers.get(CLIENT_IP_HEADER, "").strip())
    except ValueError:
        return UNKNOWN_CLIENT_KEY
    if address.version == IPV6_VERSION:
        # One IPv6 client usually controls a whole /64, so per-address keys would not limit it.
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


limiter = Limiter(key_func=client_ip_key)


async def handle_rate_limit_exceeded(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RateLimitExceeded):
        raise exc
    return problem_response(
        request,
        status=429,
        title="Too many requests",
        detail="Too many requests. Try again in a minute.",
        code="RATE_LIMITED",
    )


def register_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, handle_rate_limit_exceeded)
