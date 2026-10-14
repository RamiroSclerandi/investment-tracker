import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from investment_tracker.auth.errors import InvalidAccessTokenError

ACCESS_TOKEN_TTL = timedelta(minutes=15)
ALGORITHM = "EdDSA"
REQUIRED_CLAIMS = ["sub", "iat", "exp", "iss", "aud", "jti"]


class AccessTokens:
    def __init__(self, private_key: Ed25519PrivateKey, *, issuer: str, audience: str) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self._issuer = issuer
        self._audience = audience
        raw_public_key = self._public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.kid = hashlib.sha256(raw_public_key).hexdigest()[:16]

    def issue(self, user_id: uuid.UUID, *, now: datetime | None = None) -> tuple[str, int]:
        issued_at = now or datetime.now(UTC)
        claims = {
            "sub": str(user_id),
            "iat": issued_at,
            "exp": issued_at + ACCESS_TOKEN_TTL,
            "iss": self._issuer,
            "aud": self._audience,
            "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(
            claims, self._private_key, algorithm=ALGORITHM, headers={"kid": self.kid}
        )
        return token, int(ACCESS_TOKEN_TTL.total_seconds())

    def decode(self, token: str) -> uuid.UUID:
        try:
            if jwt.get_unverified_header(token).get("kid") != self.kid:
                raise InvalidAccessTokenError
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": REQUIRED_CLAIMS},
            )
            return uuid.UUID(claims["sub"])
        except jwt.InvalidTokenError, ValueError, TypeError:
            raise InvalidAccessTokenError from None
