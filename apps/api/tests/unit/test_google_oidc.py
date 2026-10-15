import base64
import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from investment_tracker.auth.errors import InvalidAccessTokenError
from investment_tracker.auth.google import (
    GoogleOidcClient,
    GoogleSignInError,
    OidcStateCodec,
    PendingSignIn,
)
from investment_tracker.auth.jwt import AccessTokens
from investment_tracker.auth.service import sanitize_display_name
from investment_tracker.core.rate_limit import limiter
from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app

CLIENT_ID = "client-id.apps.googleusercontent.com"
CLIENT_SECRET = "fake" * 4
WEB_BASE_URL = "https://app.example.com"
REDIRECT_URI = f"{WEB_BASE_URL}/api/v1/auth/google/callback"
START_URL = "/api/v1/auth/google/start"
CALLBACK_URL = "/api/v1/auth/google/callback"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DATABASE_URL = SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test")
CLIENT_IP = {"CF-Connecting-IP": "203.0.113.7"}
GOOGLE_KID = "fake-google-key"
GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FORGED_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class FakeGoogle:
    def __init__(self) -> None:
        self.nonce = ""
        self.subject = "google-subject-1"
        self.email = "ana@example.com"
        self.overrides: dict[str, Any] = {}
        self.id_token: str | None = None
        self.token_status = httpx.codes.OK
        self.token_body: dict[str, Any] | None = None
        self.jwks_available = True
        self.forms: list[dict[str, str]] = []
        self.urls: list[str] = []

    def claims(self, nonce: str | None = None) -> dict[str, Any]:
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": self.subject,
            "email": self.email,
            "email_verified": True,
            "name": "Ana Google",
            "nonce": self.nonce if nonce is None else nonce,
            "iat": now,
            "exp": now + timedelta(hours=1),
        }
        claims.update(self.overrides)
        return {name: value for name, value in claims.items() if value is not None}

    def issue(
        self, key: Any = GOOGLE_KEY, algorithm: str = "RS256", nonce: str | None = None
    ) -> str:
        claims = self.claims(nonce)
        return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": GOOGLE_KID})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        form = dict(parse_qsl(request.content.decode()))
        self.forms.append(form)
        if self.token_status != httpx.codes.OK:
            return httpx.Response(self.token_status, json={"error": "invalid_grant"})
        # Without a fixed nonce the code stands in for it, so concurrent flows each match.
        nonce = self.nonce or form.get("code", "")
        body = self.token_body or {"id_token": self.id_token or self.issue(nonce=nonce)}
        return httpx.Response(httpx.codes.OK, json=body)

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        if not self.jwks_available:
            raise jwt.PyJWKClientConnectionError("JWKS unreachable")
        jwk = RSAAlgorithm.to_jwk(GOOGLE_KEY.public_key(), as_dict=True)
        key_set = jwt.PyJWKSet.from_dict({"keys": [{**jwk, "kid": GOOGLE_KID, "alg": "RS256"}]})
        kid = jwt.get_unverified_header(token).get("kid")
        try:
            return key_set[str(kid)]
        except KeyError:
            raise jwt.PyJWKClientError("Unknown kid") from None

    def client(self) -> GoogleOidcClient:
        return GoogleOidcClient(
            CLIENT_ID,
            SecretStr(CLIENT_SECRET),
            REDIRECT_URI,
            signing_keys=self,
            transport=httpx.MockTransport(self.handler),
        )


def cookie_attributes(set_cookie: str) -> tuple[str, str, set[str]]:
    pair, *attributes = (part.strip() for part in set_cookie.split(";"))
    name, _, value = pair.partition("=")
    return name, value, {attribute.lower() for attribute in attributes}


def build_app(*, google: GoogleOidcClient | None, **settings: Any) -> FastAPI:
    limiter.reset()
    return create_app(
        Settings(database_url=DATABASE_URL, web_base_url=WEB_BASE_URL, _env_file=None, **settings),
        google=google,
    )


@pytest.fixture
def fake_google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def app(fake_google: FakeGoogle) -> FastAPI:
    return build_app(
        google=fake_google.client(),
        google_client_id=CLIENT_ID,
        google_client_secret=SecretStr(CLIENT_SECRET),
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


async def test_start_redirects_to_google_with_pkce_state_and_nonce(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    response = await client.get(START_URL, headers=CLIENT_IP)

    assert response.status_code == httpx.codes.FOUND
    assert response.headers["cache-control"] == "no-store"
    location = urlsplit(response.headers["location"])
    assert (location.scheme, location.netloc, location.path) == (
        "https",
        "accounts.google.com",
        "/o/oauth2/v2/auth",
    )
    query = dict(parse_qsl(location.query))
    assert query["response_type"] == "code"
    assert query["scope"] == "openid email profile"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["code_challenge_method"] == "S256"
    pending = app.state.oidc_state.decode(cookie_attributes(response.headers["set-cookie"])[1])
    assert query["state"] == pending.state
    assert query["nonce"] == pending.nonce
    assert query["code_challenge"] == s256(pending.code_verifier)
    assert 43 <= len(pending.code_verifier) <= 128


async def test_start_sets_a_short_lived_lax_cookie_scoped_to_the_google_routes(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(START_URL, headers=CLIENT_IP)

    name, value, attributes = cookie_attributes(response.headers["set-cookie"])
    assert name == "it_oidc"
    assert value
    assert {"httponly", "secure", "samesite=lax", "path=/api/v1/auth/google", "max-age=600"} <= (
        attributes
    )


async def test_every_start_uses_fresh_state_nonce_and_verifier(
    client: httpx.AsyncClient,
) -> None:
    first = dict(parse_qsl(urlsplit((await client.get(START_URL)).headers["location"]).query))
    second = dict(parse_qsl(urlsplit((await client.get(START_URL)).headers["location"]).query))

    for parameter in ("state", "nonce", "code_challenge"):
        assert first[parameter] != second[parameter]


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"google_client_id": CLIENT_ID},
        {"google_client_secret": SecretStr(CLIENT_SECRET)},
    ],
)
@pytest.mark.parametrize("url", [START_URL, f"{CALLBACK_URL}?code=c&state=s"])
async def test_google_endpoints_answer_503_when_google_is_not_configured(
    settings: dict[str, Any], url: str
) -> None:
    app = create_app(
        Settings(database_url=DATABASE_URL, web_base_url=WEB_BASE_URL, _env_file=None, **settings)
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        response = await http_client.get(url, headers=CLIENT_IP)

    assert response.status_code == httpx.codes.SERVICE_UNAVAILABLE
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "OIDC_UNAVAILABLE"


async def test_start_allows_ten_requests_per_minute_per_client_ip(
    client: httpx.AsyncClient,
) -> None:
    for _ in range(10):
        assert (await client.get(START_URL, headers=CLIENT_IP)).status_code == httpx.codes.FOUND

    limited = await client.get(START_URL, headers=CLIENT_IP)
    other_client = await client.get(START_URL, headers={"CF-Connecting-IP": "203.0.113.8"})

    assert limited.status_code == httpx.codes.TOO_MANY_REQUESTS
    assert limited.json()["code"] == "RATE_LIMITED"
    assert other_client.status_code == httpx.codes.FOUND


async def test_exchange_sends_the_verifier_and_secret_and_returns_the_identity(
    fake_google: FakeGoogle,
) -> None:
    fake_google.nonce = "expected-nonce"

    identity = await fake_google.client().exchange(
        "auth-code", code_verifier="the-verifier", nonce="expected-nonce"
    )

    assert identity.subject == "google-subject-1"
    assert identity.email == "ana@example.com"
    assert identity.email_verified is True
    assert identity.name == "Ana Google"
    assert fake_google.urls == [TOKEN_URL]
    assert fake_google.forms == [
        {
            "grant_type": "authorization_code",
            "code": "auth-code",
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code_verifier": "the-verifier",
        }
    ]


@pytest.mark.parametrize("issuer", ["https://accounts.google.com", "accounts.google.com"])
async def test_exchange_accepts_both_google_issuers(fake_google: FakeGoogle, issuer: str) -> None:
    fake_google.nonce = "n"
    fake_google.overrides = {"iss": issuer}

    identity = await fake_google.client().exchange("code", code_verifier="v", nonce="n")

    assert identity.subject == "google-subject-1"


async def test_exchange_reports_an_unverified_google_email(fake_google: FakeGoogle) -> None:
    fake_google.nonce = "n"
    fake_google.overrides = {"email_verified": False}

    identity = await fake_google.client().exchange("code", code_verifier="v", nonce="n")

    assert identity.email_verified is False


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"aud": "another-client"}, "invalid_id_token"),
        ({"iss": "https://evil.example.com"}, "invalid_id_token"),
        ({"exp": datetime.now(UTC) - timedelta(minutes=5)}, "invalid_id_token"),
        ({"iat": None}, "invalid_id_token"),
        ({"sub": None}, "invalid_id_token"),
        ({"nonce": "another-nonce"}, "nonce_mismatch"),
        ({"nonce": None}, "nonce_mismatch"),
        ({"email": None}, "missing_email"),
    ],
)
async def test_exchange_rejects_invalid_id_token_claims(
    fake_google: FakeGoogle, overrides: dict[str, Any], reason: str
) -> None:
    fake_google.nonce = "n"
    fake_google.overrides = overrides

    with pytest.raises(GoogleSignInError) as raised:
        await fake_google.client().exchange("code", code_verifier="v", nonce="n")

    assert raised.value.reason == reason


async def test_exchange_rejects_an_id_token_signed_with_another_key(
    fake_google: FakeGoogle,
) -> None:
    fake_google.nonce = "n"
    fake_google.id_token = fake_google.issue(key=FORGED_KEY)

    with pytest.raises(GoogleSignInError, match="invalid_id_token"):
        await fake_google.client().exchange("code", code_verifier="v", nonce="n")


async def test_exchange_rejects_a_symmetric_algorithm(fake_google: FakeGoogle) -> None:
    fake_google.nonce = "n"
    fake_google.id_token = fake_google.issue(
        key="shared-secret-of-32-bytes-length!", algorithm="HS256"
    )

    with pytest.raises(GoogleSignInError, match="invalid_id_token"):
        await fake_google.client().exchange("code", code_verifier="v", nonce="n")


async def test_exchange_fails_when_the_signing_keys_are_unreachable(
    fake_google: FakeGoogle,
) -> None:
    fake_google.nonce = "n"
    fake_google.jwks_available = False

    with pytest.raises(GoogleSignInError, match="invalid_id_token"):
        await fake_google.client().exchange("code", code_verifier="v", nonce="n")


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (httpx.codes.BAD_REQUEST, None),
        (httpx.codes.OK, {"access_token": "no-id-token"}),
        (httpx.codes.OK, {"id_token": 42}),
    ],
)
async def test_exchange_fails_when_google_rejects_or_omits_the_id_token(
    fake_google: FakeGoogle, status: int, body: dict[str, Any] | None
) -> None:
    fake_google.token_status = httpx.codes(status)
    fake_google.token_body = body

    with pytest.raises(GoogleSignInError, match="token_exchange_failed"):
        await fake_google.client().exchange("code", code_verifier="v", nonce="n")


async def test_exchange_fails_when_google_is_unreachable() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    google = GoogleOidcClient(
        CLIENT_ID,
        SecretStr(CLIENT_SECRET),
        REDIRECT_URI,
        signing_keys=FakeGoogle(),
        transport=httpx.MockTransport(unreachable),
    )

    with pytest.raises(GoogleSignInError, match="token_exchange_failed"):
        await google.exchange("code", code_verifier="v", nonce="n")


SIGNING_KEY = Ed25519PrivateKey.generate()


def state_codec() -> OidcStateCodec:
    return OidcStateCodec(SIGNING_KEY, issuer="investment-tracker", audience="web:oidc")


def test_the_state_cookie_round_trips_the_pending_sign_in() -> None:
    pending = PendingSignIn(state="s", nonce="n", code_verifier="v")

    assert state_codec().decode(state_codec().encode(pending)) == pending


def test_an_expired_state_cookie_is_rejected() -> None:
    issued = state_codec().encode(
        PendingSignIn(state="s", nonce="n", code_verifier="v"),
        now=datetime.now(UTC) - timedelta(minutes=11),
    )

    with pytest.raises(GoogleSignInError, match="invalid_state_cookie"):
        state_codec().decode(issued)


@pytest.mark.parametrize("cookie", [None, "", "not-a-jwt"])
def test_a_missing_or_malformed_state_cookie_is_rejected(cookie: str | None) -> None:
    with pytest.raises(GoogleSignInError, match="invalid_state_cookie"):
        state_codec().decode(cookie)


def test_an_access_token_is_not_accepted_as_a_state_cookie() -> None:
    access_tokens = AccessTokens(SIGNING_KEY, issuer="investment-tracker", audience="web")
    access_token, _ = access_tokens.issue(uuid.uuid4())

    with pytest.raises(GoogleSignInError, match="invalid_state_cookie"):
        state_codec().decode(access_token)


def test_a_state_cookie_is_not_accepted_as_an_access_token() -> None:
    access_tokens = AccessTokens(SIGNING_KEY, issuer="investment-tracker", audience="web")
    cookie = state_codec().encode(PendingSignIn(state="s", nonce="n", code_verifier="v"))

    with pytest.raises(InvalidAccessTokenError):
        access_tokens.decode(cookie)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("  Ana Google  ", "Ana Google"),
        ("Ana\nEvil\u2028Header", "Ana Evil Header"),
        ("\x00\x85\u2029", ""),
        ("x" * 100, "x" * 80),
        (None, ""),
    ],
)
def test_google_names_are_sanitized_to_the_display_name_rules(
    name: str | None, expected: str
) -> None:
    assert sanitize_display_name(name) == expected
