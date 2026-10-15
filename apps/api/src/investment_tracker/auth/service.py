import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from investment_tracker.auth.emails import password_reset_email, verification_email
from investment_tracker.auth.errors import (
    EmailNotVerifiedError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidEmailTokenError,
    InvalidRefreshTokenError,
    UnauthorizedError,
)
from investment_tracker.auth.jwt import AccessTokens
from investment_tracker.auth.models import (
    Currency,
    EmailToken,
    EmailTokenPurpose,
    RefreshToken,
    User,
)
from investment_tracker.auth.passwords import (
    DUMMY_PASSWORD_HASH,
    hash_password_async,
    verify_password_async,
)
from investment_tracker.auth.repository import (
    EmailTokenRepository,
    RefreshTokenRepository,
    UserRepository,
)
from investment_tracker.auth.tokens import hash_token, new_token
from investment_tracker.core.email import EmailMessage
from investment_tracker.core.settings import Settings

VERIFY_TOKEN_TTL = timedelta(hours=24)
RESET_TOKEN_TTL = timedelta(minutes=30)
REFRESH_TOKEN_TTL = timedelta(days=30)
SESSION_MAX_LIFETIME = timedelta(days=60)
USER_AGENT_MAX_LENGTH = 256

logger = structlog.get_logger()


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._tokens = EmailTokenRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def register(self, email: str, password: str, display_name: str) -> EmailMessage | None:
        # Hashing runs on every request so response time does not reveal existing accounts.
        password_hash = await hash_password_async(password)
        try:
            async with self._session.begin():
                message = await self._register_user(email, password_hash, display_name)
        except IntegrityError:
            # A concurrent registration of the same email won the race; answer the same way.
            return None
        return message

    async def verify_email(self, raw_token: str, password: str) -> None:
        token_hash = hash_token(raw_token)
        # Argon2 runs between two short transactions so no row lock is held during it.
        async with self._session.begin():
            token = await self._tokens.get_active(
                token_hash, EmailTokenPurpose.VERIFY_EMAIL, datetime.now(UTC)
            )
            user = await self._users.get(token.user_id) if token else None
        if user is None or not user.is_active:
            await verify_password_async(DUMMY_PASSWORD_HASH, password)
            raise InvalidEmailTokenError
        known_hash = user.password_hash
        new_hash = await self._prove_password(known_hash, password)
        await self._apply_verification(user.id, token_hash, known_hash, new_hash)

    async def _prove_password(self, password_hash: str | None, password: str) -> str | None:
        if password_hash is None:
            return await hash_password_async(password)
        if not await verify_password_async(password_hash, password):
            raise InvalidEmailTokenError
        return None

    async def _apply_verification(
        self,
        user_id: uuid.UUID,
        token_hash: str,
        known_hash: str | None,
        new_hash: str | None,
    ) -> None:
        now = datetime.now(UTC)
        # User before token: the same lock order as register and resend, so they cannot deadlock.
        # Raising here rolls back, leaving the token unused for the real owner.
        async with self._session.begin():
            user = await self._users.get_for_update(user_id)
            token = await self._tokens.get_active_for_update(
                token_hash, EmailTokenPurpose.VERIFY_EMAIL, now
            )
            if (
                user is None
                or not user.is_active
                or user.password_hash != known_hash
                or token is None
                or token.user_id != user.id
            ):
                raise InvalidEmailTokenError
            if new_hash is not None:
                user.password_hash = new_hash
            token.used_at = now
            if user.email_verified_at is None:
                user.email_verified_at = now

    async def resend_verification(self, email: str) -> EmailMessage | None:
        async with self._session.begin():
            user = await self._users.get_by_email_for_update(email)
            if user is None or not user.is_active or user.email_verified_at is not None:
                return None
            return await self._replace_verification_token(user)

    async def request_password_reset(self, email: str) -> EmailMessage | None:
        # Unverified accounts may reset: the link proves mailbox ownership like verification.
        async with self._session.begin():
            user = await self._users.get_by_email_for_update(email)
            if user is None or not user.is_active:
                return None
            now = datetime.now(UTC)
            await self._tokens.invalidate_active(user.id, EmailTokenPurpose.RESET_PASSWORD, now)
            raw, token_hash = new_token()
            self._tokens.add(
                EmailToken(
                    user_id=user.id,
                    purpose=EmailTokenPurpose.RESET_PASSWORD,
                    token_hash=token_hash,
                    expires_at=now + RESET_TOKEN_TTL,
                )
            )
            return password_reset_email(
                to=user.email,
                display_name=user.display_name,
                web_base_url=self._settings.web_base_url,
                raw_token=raw,
                ttl=RESET_TOKEN_TTL,
            )

    async def reset_password(self, raw_token: str, password: str) -> None:
        token_hash = hash_token(raw_token)
        # Hashed before the transaction, for every token, so no lock is held during argon2
        # and a bad token costs the same time as a good one.
        new_hash = await hash_password_async(password)
        now = datetime.now(UTC)
        async with self._session.begin():
            pending = await self._tokens.get_active(
                token_hash, EmailTokenPurpose.RESET_PASSWORD, now
            )
            # User before token: the same lock order as verification, register and logout-all.
            user = await self._users.get_for_update(pending.user_id) if pending else None
            token = await self._tokens.get_active_for_update(
                token_hash, EmailTokenPurpose.RESET_PASSWORD, now
            )
            if user is None or not user.is_active or token is None or token.user_id != user.id:
                raise InvalidEmailTokenError
            user.password_hash = new_hash
            if user.email_verified_at is None:
                user.email_verified_at = now
            token.used_at = now
            await self._refresh_tokens.lock_all_for_user(user.id)
            await self._refresh_tokens.revoke_all_for_user(user.id, now)

    async def _register_user(
        self, email: str, password_hash: str, display_name: str
    ) -> EmailMessage | None:
        user = await self._users.get_by_email_for_update(email)
        if user is None:
            user = User(email=email, password_hash=password_hash, display_name=display_name)
            await self._users.add(user)
            return self._issue_verification_token(user)
        if user.email_verified_at is not None or not user.is_active:
            return None
        # The mailbox owner may not be the one registering now, so a repeated registration
        # never keeps a password: whoever verifies sets one through reset.
        user.password_hash = None
        return await self._replace_verification_token(user)

    async def _replace_verification_token(self, user: User) -> EmailMessage:
        await self._tokens.invalidate_active(
            user.id, EmailTokenPurpose.VERIFY_EMAIL, datetime.now(UTC)
        )
        return self._issue_verification_token(user)

    def _issue_verification_token(self, user: User) -> EmailMessage:
        raw, token_hash = new_token()
        self._tokens.add(
            EmailToken(
                user_id=user.id,
                purpose=EmailTokenPurpose.VERIFY_EMAIL,
                token_hash=token_hash,
                expires_at=datetime.now(UTC) + VERIFY_TOKEN_TTL,
            )
        )
        return verification_email(
            to=user.email,
            display_name=user.display_name,
            web_base_url=self._settings.web_base_url,
            raw_token=raw,
        )


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    expires_in: int
    refresh_token: str


class SessionService:
    def __init__(self, session: AsyncSession, access_tokens: AccessTokens) -> None:
        self._session = session
        self._access_tokens = access_tokens
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def login(
        self, email: str, password: str, *, user_agent: str | None, ip: str | None
    ) -> IssuedSession:
        # Argon2 runs outside any transaction so no connection or row lock is held during it.
        async with self._session.begin():
            user = await self._users.get_by_email(email)
        if user is None or user.password_hash is None or not user.is_active:
            await verify_password_async(DUMMY_PASSWORD_HASH, password)
            raise InvalidCredentialsError
        if not await verify_password_async(user.password_hash, password):
            raise InvalidCredentialsError
        # Revealed only after the password checks out, so it cannot be used to probe accounts.
        if user.email_verified_at is None:
            raise EmailNotVerifiedError
        refresh_token = await self._start_family(user.id, user.password_hash, user_agent, ip)
        access_token, expires_in = self._access_tokens.issue(user.id)
        return IssuedSession(access_token, expires_in, refresh_token)

    async def authenticate(self, access_token: str) -> User:
        try:
            user_id = self._access_tokens.decode(access_token)
        except InvalidAccessTokenError:
            raise UnauthorizedError from None
        async with self._session.begin():
            user = await self._users.get(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError
        return user

    async def refresh(
        self, raw_token: str | None, *, user_agent: str | None, ip: str | None
    ) -> IssuedSession:
        if not raw_token:
            raise InvalidRefreshTokenError
        new_raw, new_hash = new_token()
        # Revocations must commit, so the outcome is decided inside the transaction and the
        # error is raised after it.
        async with self._session.begin():
            user_id = await self._rotate(hash_token(raw_token), new_hash, user_agent, ip)
        if user_id is None:
            raise InvalidRefreshTokenError
        access_token, expires_in = self._access_tokens.issue(user_id)
        return IssuedSession(access_token, expires_in, new_raw)

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        token_hash = hash_token(raw_token)
        async with self._session.begin():
            if await self._lock_owner_of(token_hash) is None:
                return
            family = await self._refresh_tokens.lock_family_of(token_hash)
            if family:
                await self._refresh_tokens.revoke_family(family[0].family_id, datetime.now(UTC))

    async def logout_all(self, user_id: uuid.UUID) -> None:
        async with self._session.begin():
            await self._users.get_for_update(user_id)
            await self._refresh_tokens.lock_all_for_user(user_id)
            await self._refresh_tokens.revoke_all_for_user(user_id, datetime.now(UTC))

    async def _lock_owner_of(self, token_hash: str) -> User | None:
        # User row before token rows: the same lock order as login and verification, so
        # refresh, logout and logout-all cannot deadlock with them or with each other.
        token = await self._refresh_tokens.get_by_hash(token_hash)
        if token is None:
            return None
        return await self._users.get_for_update(token.user_id)

    async def _rotate(
        self, token_hash: str, new_hash: str, user_agent: str | None, ip: str | None
    ) -> uuid.UUID | None:
        now = datetime.now(UTC)
        user = await self._lock_owner_of(token_hash)
        family = await self._refresh_tokens.lock_family_of(token_hash)
        token = next((row for row in family if row.token_hash == token_hash), None)
        if token is None or token.revoked_at is not None or token.expires_at <= now:
            return None
        if token.rotated_at is not None:
            logger.warning("refresh_token_reuse_detected", family_id=str(token.family_id))
            await self._refresh_tokens.revoke_family(token.family_id, now)
            return None
        session_end = min(row.created_at for row in family) + SESSION_MAX_LIFETIME
        if user is None or not user.is_active or now >= session_end:
            await self._refresh_tokens.revoke_family(token.family_id, now)
            return None
        token.rotated_at = now
        expires_at = min(now + REFRESH_TOKEN_TTL, session_end)
        self._add_refresh_token(user.id, token.family_id, new_hash, expires_at, user_agent, ip)
        return user.id

    async def _start_family(
        self, user_id: uuid.UUID, known_hash: str, user_agent: str | None, ip: str | None
    ) -> str:
        raw, token_hash = new_token()
        now = datetime.now(UTC)
        async with self._session.begin():
            user = await self._users.get_for_update(user_id)
            # The account may have changed while argon2 ran.
            if user is None or not user.is_active or user.password_hash != known_hash:
                raise InvalidCredentialsError
            self._add_refresh_token(
                user_id, uuid.uuid4(), token_hash, now + REFRESH_TOKEN_TTL, user_agent, ip
            )
        return raw

    def _add_refresh_token(
        self,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> None:
        self._refresh_tokens.add(
            RefreshToken(
                user_id=user_id,
                family_id=family_id,
                token_hash=token_hash,
                expires_at=expires_at,
                user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
                ip=ip,
            )
        )


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def update(
        self,
        user_id: uuid.UUID,
        *,
        display_name: str | None,
        preferred_currency: Currency | None,
    ) -> User:
        async with self._session.begin():
            user = await self._users.get_for_update(user_id)
            if user is None or not user.is_active:
                raise UnauthorizedError
            if display_name is not None:
                user.display_name = display_name
            if preferred_currency is not None:
                user.preferred_currency = preferred_currency
        return user
