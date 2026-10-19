import hmac
import ipaddress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from investment_tracker.core.errors import problem_response

# Render's Cloudflare edge rejects forged values of this header; every other client-IP header
# can be forged on the direct-to-Render path.
CLIENT_IP_HEADER = "cf-connecting-ip"
# Forgeable on the direct-to-Render path, so trusted only with the secret the Vercel proxy sends.
PROXIED_CLIENT_IP_HEADER = "x-vercel-forwarded-for"
PROXY_VERIFICATION_HEADER = "x-proxy-secret"
UNKNOWN_CLIENT_KEY = "unknown-client"
IPV6_VERSION = 6


def is_proxy_verified(request: Request) -> bool:
    secret = request.app.state.settings.proxy_shared_secret
    if secret is None:
        return False
    supplied = request.headers.get(PROXY_VERIFICATION_HEADER, "")
    return hmac.compare_digest(supplied.encode(), secret.get_secret_value().encode())


def _raw_client_ip(request: Request) -> str:
    if is_proxy_verified(request):
        return request.headers.get(PROXIED_CLIENT_IP_HEADER, "").split(",")[0]
    return request.headers.get(CLIENT_IP_HEADER, "")


def client_ip(request: Request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address(_raw_client_ip(request).strip())
    except ValueError:
        return None
    # A zone suffix never comes from a real client and would give each suffix its own bucket.
    if isinstance(address, ipaddress.IPv6Address) and address.scope_id is not None:
        return None
    return address


def client_ip_key(request: Request) -> str:
    address = client_ip(request)
    if address is None:
        return UNKNOWN_CLIENT_KEY
    if address.version == IPV6_VERSION:
        # One IPv6 client usually controls a whole /64, so per-address keys would not limit it.
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


limiter = Limiter(key_func=client_ip_key)


class KeyedRateLimitExceededError(Exception):
    pass


class KeyedRateLimiter:
    # slowapi key functions cannot read the parsed body, so body-keyed limits live here.
    def __init__(self, limit: str) -> None:
        self._item = parse(limit)
        self._storage = MemoryStorage()
        self._strategy = MovingWindowRateLimiter(self._storage)

    def hit(self, key: str) -> None:
        if not self._strategy.hit(self._item, key):
            raise KeyedRateLimitExceededError

    def allow(self, key: str) -> bool:
        return self._strategy.hit(self._item, key)

    def reset(self) -> None:
        self._storage.reset()


login_limiter = KeyedRateLimiter("5/minute")
# Per address and client, so one client cannot use up another person's reset emails.
forgot_client_email_limiter = KeyedRateLimiter("3/hour")
# Caps how many reset emails one address receives from every client together.
forgot_email_limiter = KeyedRateLimiter("10/hour")

# Every limit that answers 429 is per minute, so one full window is the longest wait to announce.
RATE_LIMITED_RETRY_AFTER_SECONDS = 60


async def handle_rate_limit_exceeded(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RateLimitExceeded | KeyedRateLimitExceededError):
        raise exc
    response = problem_response(
        request,
        status=429,
        title="Too many requests",
        detail="Too many requests. Try again in a minute.",
        code="RATE_LIMITED",
    )
    response.headers["Retry-After"] = str(RATE_LIMITED_RETRY_AFTER_SECONDS)
    return response


def register_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, handle_rate_limit_exceeded)
    app.add_exception_handler(KeyedRateLimitExceededError, handle_rate_limit_exceeded)
