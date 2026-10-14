import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from investment_tracker.auth.emails import verification_email
from investment_tracker.auth.errors import InvalidEmailTokenError
from investment_tracker.auth.models import EmailToken, EmailTokenPurpose, User
from investment_tracker.auth.passwords import hash_password
from investment_tracker.auth.repository import EmailTokenRepository, UserRepository
from investment_tracker.auth.tokens import hash_token, new_token
from investment_tracker.core.email import EmailMessage
from investment_tracker.core.settings import Settings

VERIFY_TOKEN_TTL = timedelta(hours=24)


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._tokens = EmailTokenRepository(session)

    async def register(self, email: str, password: str, display_name: str) -> EmailMessage | None:
        # Hashing runs on every request so response time does not reveal existing accounts.
        password_hash = await asyncio.to_thread(hash_password, password)
        try:
            async with self._session.begin():
                message = await self._register_user(email, password_hash, display_name)
        except IntegrityError:
            # A concurrent registration of the same email won the race; answer the same way.
            return None
        return message

    async def verify_email(self, raw_token: str) -> None:
        now = datetime.now(UTC)
        async with self._session.begin():
            token = await self._tokens.get_active_for_update(
                hash_token(raw_token), EmailTokenPurpose.VERIFY_EMAIL, now
            )
            if token is None:
                raise InvalidEmailTokenError
            token.used_at = now
            user = await self._users.get(token.user_id)
            if user is not None and user.email_verified_at is None:
                user.email_verified_at = now

    async def resend_verification(self, email: str) -> EmailMessage | None:
        async with self._session.begin():
            user = await self._users.get_by_email_for_update(email)
            if user is None or not user.is_active or user.email_verified_at is not None:
                return None
            return await self._replace_verification_token(user)

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
