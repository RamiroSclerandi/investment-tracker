import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from investment_tracker.auth.google import GoogleOidcClient

CLIENT_ID = "client-id.apps.googleusercontent.com"
CLIENT_SECRET = "fake" * 4
WEB_BASE_URL = "https://app.example.com"
REDIRECT_URI = f"{WEB_BASE_URL}/api/v1/auth/google/callback"
START_URL = "/api/v1/auth/google/start"
CALLBACK_URL = "/api/v1/auth/google/callback"
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
