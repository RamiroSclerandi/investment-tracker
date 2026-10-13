from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from investment_tracker.core.db import create_engine, create_sessionmaker
from investment_tracker.core.errors import register_exception_handlers
from investment_tracker.core.logging import configure_logging
from investment_tracker.core.request_id import RequestIdMiddleware
from investment_tracker.core.settings import Settings

API_PREFIX = "/api/v1"


def create_app(settings: Settings) -> FastAPI:
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Investment Tracker", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(APIRouter(prefix=API_PREFIX))
    return app


def build_app() -> FastAPI:
    return create_app(Settings())
