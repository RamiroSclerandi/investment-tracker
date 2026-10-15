import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

from investment_tracker.core.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=300,
        hide_parameters=True,
        # The transaction pooler hands each transaction a different server connection, so
        # prepared statements cannot be cached or reuse a name across transactions.
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": _unique_statement_name,
        },
    )


def _unique_statement_name() -> str:
    return f"__asyncpg_{uuid.uuid4()}__"


class RequestSession(Session):
    pass


USER_ID_KEY = "user_id"


@event.listens_for(RequestSession, "after_begin")
def _set_transaction_user(
    session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    user_id = session.info.get(USER_ID_KEY)
    if user_id is not None:
        connection.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_id)}
        )


def set_session_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    session.info[USER_ID_KEY] = user_id


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, sync_session_class=RequestSession)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
