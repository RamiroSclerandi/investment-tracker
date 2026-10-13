from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


async def test_lifespan_creates_and_disposes_engine(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        engine: AsyncEngine = app.state.engine
        pool_in_use = engine.pool
        assert isinstance(app.state.sessionmaker, async_sessionmaker)
        assert engine.pool is pool_in_use

    assert engine.pool is not pool_in_use


async def test_engine_uses_configured_pool(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        pool = app.state.engine.pool

        assert pool.size() == 5
        assert pool._max_overflow == 5
