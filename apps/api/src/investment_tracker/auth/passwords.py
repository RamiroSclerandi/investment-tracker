import asyncio
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
# Each argon2 call holds 64 MiB and a core; the cap stops unauthenticated bursts from
# exhausting memory or starving the event loop's thread pool.
_argon2_slots = asyncio.Semaphore(2)
# Verified against when there is no real hash, so failures cost the same argon2 work.
DUMMY_PASSWORD_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


async def hash_password_async(password: str) -> str:
    async with _argon2_slots:
        return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    async with _argon2_slots:
        return await asyncio.to_thread(verify_password, password_hash, password)
