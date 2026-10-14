from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from investment_tracker.auth.router import router as auth_router
from investment_tracker.core.db import create_engine, create_sessionmaker
from investment_tracker.core.email import EmailSender, SmtpEmailSender, UnconfiguredEmailSender
from investment_tracker.core.errors import register_exception_handlers
from investment_tracker.core.logging import configure_logging
from investment_tracker.core.rate_limit import register_rate_limiting
from investment_tracker.core.request_id import RequestIdMiddleware
from investment_tracker.core.settings import Settings
from investment_tracker.ops.router import router as ops_router

API_PREFIX = "/api/v1"


def default_email_sender(settings: Settings) -> EmailSender:
    if settings.smtp_url is None:
        return UnconfiguredEmailSender()
    return SmtpEmailSender(settings.smtp_url.get_secret_value(), settings.email_from)


def create_app(settings: Settings, email_sender: EmailSender | None = None) -> FastAPI:
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

    docs_enabled = settings.environment != "production"
    app = FastAPI(
        title="Investment Tracker",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.email_sender = email_sender or default_email_sender(settings)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    register_rate_limiting(app)
    api_router = APIRouter(prefix=API_PREFIX)
    api_router.include_router(ops_router)
    api_router.include_router(auth_router)
    app.include_router(api_router)
    return app


def build_app() -> FastAPI:
    return create_app(Settings())
