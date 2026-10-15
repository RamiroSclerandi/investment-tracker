import asyncio
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
GOOGLE_SCOPES = "openid email profile"
GOOGLE_HTTP_TIMEOUT_SECONDS = 10.0
ID_TOKEN_REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss"]
STATE_COOKIE_TTL = timedelta(minutes=10)
STATE_ALGORITHM = "EdDSA"
STATE_REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "state", "nonce", "cv"]


class GoogleSignInError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str | None


@dataclass(frozen=True)
class PendingSignIn:
    state: str
    nonce: str
    code_verifier: str


class SigningKeySource(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


class GoogleIdentityProvider(Protocol):
    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str: ...

    async def exchange(self, code: str, *, code_verifier: str, nonce: str) -> GoogleIdentity: ...


def google_signing_keys() -> SigningKeySource:
    return jwt.PyJWKClient(GOOGLE_JWKS_URL, timeout=int(GOOGLE_HTTP_TIMEOUT_SECONDS))


class GoogleOidcClient:
    def __init__(
        self,
        client_id: str,
        client_secret: SecretStr,
        redirect_uri: str,
        *,
        signing_keys: SigningKeySource,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._signing_keys = signing_keys
        self._transport = transport

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "scope": GOOGLE_SCOPES,
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{GOOGLE_AUTHORIZATION_URL}?{query}"

    async def exchange(self, code: str, *, code_verifier: str, nonce: str) -> GoogleIdentity:
        id_token = await self._fetch_id_token(code, code_verifier)
        claims = await asyncio.to_thread(self._decode, id_token)
        if not hmac.compare_digest(str(claims.get("nonce", "")).encode(), nonce.encode()):
            raise GoogleSignInError("nonce_mismatch")
        email = claims.get("email")
        if not isinstance(email, str) or not email:
            raise GoogleSignInError("missing_email")
        name = claims.get("name")
        return GoogleIdentity(
            subject=str(claims["sub"]),
            email=email,
            email_verified=claims.get("email_verified") is True,
            name=name if isinstance(name, str) else None,
        )

    async def _fetch_id_token(self, code: str, code_verifier: str) -> str:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "client_secret": self._client_secret.get_secret_value(),
            "code_verifier": code_verifier,
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=GOOGLE_HTTP_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(GOOGLE_TOKEN_URL, data=form)
            id_token = response.json().get("id_token") if response.is_success else None
        except httpx.HTTPError, ValueError, AttributeError:
            id_token = None
        if not isinstance(id_token, str):
            raise GoogleSignInError("token_exchange_failed")
        return id_token

    def _decode(self, id_token: str) -> dict[str, Any]:
        try:
            signing_key = self._signing_keys.get_signing_key_from_jwt(id_token)
            claims: dict[str, Any] = jwt.decode(
                id_token,
                signing_key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=GOOGLE_ISSUERS,
                options={"require": ID_TOKEN_REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError:
            raise GoogleSignInError("invalid_id_token") from None
        return claims


class OidcStateCodec:
    def __init__(self, private_key: Ed25519PrivateKey, *, issuer: str, audience: str) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self._issuer = issuer
        self._audience = audience

    def encode(self, pending: PendingSignIn, *, now: datetime | None = None) -> str:
        issued_at = now or datetime.now(UTC)
        claims = {
            "iss": self._issuer,
            "aud": self._audience,
            "iat": issued_at,
            "exp": issued_at + STATE_COOKIE_TTL,
            "state": pending.state,
            "nonce": pending.nonce,
            "cv": pending.code_verifier,
        }
        return jwt.encode(claims, self._private_key, algorithm=STATE_ALGORITHM)

    def decode(self, cookie: str | None) -> PendingSignIn:
        if not cookie:
            raise GoogleSignInError("invalid_state_cookie")
        try:
            claims = jwt.decode(
                cookie,
                self._public_key,
                algorithms=[STATE_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": STATE_REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError:
            raise GoogleSignInError("invalid_state_cookie") from None
        return PendingSignIn(
            state=str(claims["state"]), nonce=str(claims["nonce"]), code_verifier=str(claims["cv"])
        )
