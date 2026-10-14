import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from investment_tracker.auth.errors import InvalidAccessTokenError
from investment_tracker.auth.jwt import AccessTokens

ISSUER = "investment-tracker"
AUDIENCE = "investment-tracker-web"


def _access_tokens(key: Ed25519PrivateKey | None = None) -> AccessTokens:
    return AccessTokens(key or Ed25519PrivateKey.generate(), issuer=ISSUER, audience=AUDIENCE)


def _expected_kid(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def _sign(key: Ed25519PrivateKey, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "jti": uuid.uuid4().hex,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": _expected_kid(key)})


def test_an_issued_token_decodes_back_to_its_user() -> None:
    tokens = _access_tokens()
    user_id = uuid.uuid4()

    token, expires_in = tokens.issue(user_id)

    assert tokens.decode(token) == user_id
    assert expires_in == 900


def test_an_issued_token_carries_the_expected_claims_and_header() -> None:
    key = Ed25519PrivateKey.generate()
    user_id = uuid.uuid4()

    token, _ = _access_tokens(key).issue(user_id)

    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert header["alg"] == "EdDSA"
    assert header["kid"] == _expected_kid(key)
    assert claims["sub"] == str(user_id)
    assert claims["iss"] == ISSUER
    assert claims["aud"] == AUDIENCE
    assert claims["exp"] - claims["iat"] == 900
    assert len(claims["jti"]) == 32
    int(claims["jti"], 16)


def test_every_issued_token_has_a_unique_id() -> None:
    tokens = _access_tokens()
    user_id = uuid.uuid4()

    first, _ = tokens.issue(user_id)
    second, _ = tokens.issue(user_id)

    first_claims = jwt.decode(first, options={"verify_signature": False})
    second_claims = jwt.decode(second, options={"verify_signature": False})
    assert first_claims["jti"] != second_claims["jti"]


def test_an_expired_token_is_rejected() -> None:
    tokens = _access_tokens()
    token, _ = tokens.issue(uuid.uuid4(), now=datetime.now(UTC) - timedelta(minutes=16))

    with pytest.raises(InvalidAccessTokenError):
        tokens.decode(token)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"aud": "someone-else"}, id="wrong audience"),
        pytest.param({"iss": "someone-else"}, id="wrong issuer"),
        pytest.param({"sub": "not-a-uuid"}, id="subject that is not a uuid"),
    ],
)
def test_a_token_with_invalid_claims_is_rejected(overrides: dict[str, object]) -> None:
    key = Ed25519PrivateKey.generate()
    token = _sign(key, **overrides)

    with pytest.raises(InvalidAccessTokenError):
        _access_tokens(key).decode(token)


def test_a_token_without_an_id_is_rejected() -> None:
    key = Ed25519PrivateKey.generate()
    claims = jwt.decode(_sign(key), options={"verify_signature": False})
    del claims["jti"]
    token = jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": _expected_kid(key)})

    with pytest.raises(InvalidAccessTokenError):
        _access_tokens(key).decode(token)


def test_a_token_signed_with_another_key_is_rejected() -> None:
    token, _ = _access_tokens().issue(uuid.uuid4())

    with pytest.raises(InvalidAccessTokenError):
        _access_tokens().decode(token)


def test_a_token_with_a_forged_kid_is_rejected() -> None:
    key = Ed25519PrivateKey.generate()
    claims = jwt.decode(_sign(key), options={"verify_signature": False})
    token = jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": "0" * 16})

    with pytest.raises(InvalidAccessTokenError):
        _access_tokens(key).decode(token)


def test_an_unsigned_token_is_rejected() -> None:
    key = Ed25519PrivateKey.generate()
    claims = jwt.decode(_sign(key), options={"verify_signature": False})
    token = jwt.encode(claims, "", algorithm="none", headers={"kid": _expected_kid(key)})

    with pytest.raises(InvalidAccessTokenError):
        _access_tokens(key).decode(token)


@pytest.mark.parametrize("garbage", ["", "garbage", "a.b.c", "Bearer x"])
def test_garbage_is_rejected(garbage: str) -> None:
    with pytest.raises(InvalidAccessTokenError):
        _access_tokens().decode(garbage)
