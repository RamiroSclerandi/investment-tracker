from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.pool import QueuePool

from investment_tracker.core.db import create_engine
from investment_tracker.core.settings import Settings

DATABASE_URL = SecretStr("postgresql+asyncpg://user:pass@localhost:5432/test")


class ConnectAttemptedError(Exception):
    pass


async def _connect_params() -> dict[str, Any]:
    engine = create_engine(Settings(database_url=DATABASE_URL, _env_file=None))
    captured: dict[str, Any] = {}

    @event.listens_for(engine.sync_engine, "do_connect")
    def capture(_dialect: object, _record: object, _args: object, params: dict[str, Any]) -> None:
        captured.update(params)
        raise ConnectAttemptedError

    with pytest.raises(ConnectAttemptedError):
        async with engine.connect():
            pass
    await engine.dispose()
    return captured


async def test_engine_disables_asyncpg_and_sqlalchemy_statement_caches() -> None:
    params = await _connect_params()

    assert params["statement_cache_size"] == 0
    assert params["prepared_statement_cache_size"] == 0


async def test_engine_names_each_prepared_statement_uniquely() -> None:
    name_statement = (await _connect_params())["prepared_statement_name_func"]

    first, second = name_statement(), name_statement()

    assert first != second
    assert first.startswith("__asyncpg_")
    assert first.endswith("__")


def test_engine_keeps_a_queue_pool_with_pre_ping() -> None:
    engine = create_engine(Settings(database_url=DATABASE_URL, _env_file=None))

    assert isinstance(engine.pool, QueuePool)
    assert engine.pool._pre_ping is True
