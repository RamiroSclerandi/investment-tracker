import uuid
from datetime import datetime

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from investment_tracker.auth.models import EmailToken, EmailTokenPurpose, RefreshToken, User


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


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, token: RefreshToken) -> None:
        self._session.add(token)


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
