import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from investment_tracker.auth.models import EmailToken, EmailTokenPurpose, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email_for_update(self, email: str) -> User | None:
        statement = select(User).where(User.email == email).with_for_update()
        return await self._session.scalar(statement)

    async def add(self, user: User) -> None:
        self._session.add(user)
        await self._session.flush()


class EmailTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, token: EmailToken) -> None:
        self._session.add(token)

    async def get_active_for_update(
        self, token_hash: str, purpose: EmailTokenPurpose, now: datetime
    ) -> EmailToken | None:
        statement = (
            select(EmailToken)
            .where(
                EmailToken.token_hash == token_hash,
                EmailToken.purpose == purpose,
                EmailToken.used_at.is_(None),
                EmailToken.expires_at > now,
            )
            .with_for_update()
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
