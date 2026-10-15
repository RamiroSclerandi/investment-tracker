import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from investment_tracker.auth.errors import PasswordHashingBusyError

_hasher = PasswordHasher()
# Each argon2 call holds 64 MiB and a core; the cap stops unauthenticated bursts from
# exhausting memory or starving the event loop's thread pool.
_argon2_slots = asyncio.Semaphore(2)
# Bounded so a burst is shed with 503 instead of queueing requests without limit.
ARGON2_WAIT_SECONDS = 5.0
# Verified against when there is no real hash, so failures cost the same argon2 work.
DUMMY_PASSWORD_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


@asynccontextmanager
async def _argon2_slot() -> AsyncIterator[None]:
    # The module global can be swapped (tests do), so release the semaphore that was acquired.
    slots = _argon2_slots
    try:
        async with asyncio.timeout(ARGON2_WAIT_SECONDS):
            await slots.acquire()
    except TimeoutError:
        raise PasswordHashingBusyError from None
    try:
        yield
    finally:
        slots.release()


async def hash_password_async(password: str) -> str:
    async with _argon2_slot():
        return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    async with _argon2_slot():
        return await asyncio.to_thread(verify_password, password_hash, password)
