import uuid
from datetime import datetime

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from investment_tracker.auth.models import (
    EmailToken,
    EmailTokenPurpose,
    OAuthAccount,
    OAuthProvider,
    RefreshToken,
    User,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_for_update(self, user_id: uuid.UUID) -> User | None:
        # populate_existing refreshes a copy already in the identity map from an earlier read.
        return await self._session.get(User, user_id, with_for_update=True, populate_existing=True)

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def get_by_email_for_update(self, email: str) -> User | None:
        statement = select(User).where(User.email == email).with_for_update()
        return await self._session.scalar(statement)

    async def add(self, user: User) -> None:
        self._session.add(user)
        await self._session.flush()


class OAuthAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, provider: OAuthProvider, subject: str) -> OAuthAccount | None:
        return await self._session.scalar(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider, OAuthAccount.provider_subject == subject
            )
        )

    async def add(self, account: OAuthAccount) -> None:
        self._session.add(account)
        await self._session.flush()


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, token: RefreshToken) -> None:
        self._session.add(token)

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return await self._session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

    # Every writer locks rows in id order before changing them, so concurrent refreshes and
    # revocations serialize without deadlocking, and a later statement sees any token a
    # concurrent rotation inserted.
    async def lock_family_of(self, token_hash: str) -> list[RefreshToken]:
        family_id = (
            select(RefreshToken.family_id)
            .where(RefreshToken.token_hash == token_hash)
            .scalar_subquery()
        )
        statement = (
            select(RefreshToken)
            .where(RefreshToken.family_id == family_id)
            .order_by(RefreshToken.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(await self._session.scalars(statement))

    async def lock_all_for_user(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            select(RefreshToken.id)
            .where(RefreshToken.user_id == user_id)
            .order_by(RefreshToken.id)
            .with_for_update()
        )

    async def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )


class EmailTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, token: EmailToken) -> None:
        self._session.add(token)

    async def get_active(
        self, token_hash: str, purpose: EmailTokenPurpose, now: datetime
    ) -> EmailToken | None:
        return await self._session.scalar(_active_token(token_hash, purpose, now))

    async def get_active_for_update(
        self, token_hash: str, purpose: EmailTokenPurpose, now: datetime
    ) -> EmailToken | None:
        statement = (
            _active_token(token_hash, purpose, now)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return await self._session.scalar(statement)

    async def invalidate_active(
        self, user_id: uuid.UUID, purpose: EmailTokenPurpose, now: datetime
    ) -> None:
        await self._session.execute(
            update(EmailToken)
            .where(
                EmailToken.user_id == user_id,
                EmailToken.purpose == purpose,
                EmailToken.used_at.is_(None),
            )
            .values(used_at=now)
        )


def _active_token(token_hash: str, purpose: EmailTokenPurpose, now: datetime) -> Select[EmailToken]:
    return select(EmailToken).where(
        EmailToken.token_hash == token_hash,
        EmailToken.purpose == purpose,
        EmailToken.used_at.is_(None),
        EmailToken.expires_at > now,
    )
