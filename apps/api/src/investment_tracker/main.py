from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, FastAPI

from investment_tracker.auth.errors import (
    InvalidRefreshTokenError,
    OidcUnavailableError,
    PasswordHashingBusyError,
    UnauthorizedError,
    handle_oidc_unavailable,
    handle_password_hashing_busy,
    handle_unauthorized,
)
from investment_tracker.auth.google import (
    GoogleIdentityProvider,
    GoogleOidcClient,
    OidcStateCodec,
    google_signing_keys,
)
from investment_tracker.auth.jwt import AccessTokens
from investment_tracker.auth.router import handle_invalid_refresh_token
from investment_tracker.auth.router import router as auth_router
from investment_tracker.core.db import create_engine, create_sessionmaker
from investment_tracker.core.email import EmailSender, SmtpEmailSender, UnconfiguredEmailSender
from investment_tracker.core.errors import register_exception_handlers
from investment_tracker.core.logging import configure_logging
from investment_tracker.core.rate_limit import register_rate_limiting
from investment_tracker.core.request_id import RequestIdMiddleware
from investment_tracker.core.settings import Settings, load_jwt_private_key
from investment_tracker.ops.router import router as ops_router

API_PREFIX = "/api/v1"

logger = structlog.get_logger()


def default_email_sender(settings: Settings) -> EmailSender:
    if settings.smtp_url is None:
        return UnconfiguredEmailSender()
    return SmtpEmailSender(settings.smtp_url.get_secret_value(), settings.email_from)


def signing_key(settings: Settings) -> Ed25519PrivateKey:
    if settings.jwt_private_key is not None:
        return load_jwt_private_key(settings.jwt_private_key)
    # Settings reject a missing key in production, so this only runs in development and tests.
    return Ed25519PrivateKey.generate()


def default_google_client(settings: Settings) -> GoogleIdentityProvider | None:
    if settings.google_client_id is None or settings.google_client_secret is None:
        return None
    # The web app proxies /api, so Google redirects back to the web origin and cookies land there.
    return GoogleOidcClient(
        settings.google_client_id,
        settings.google_client_secret,
        f"{settings.web_base_url}{API_PREFIX}/auth/google/callback",
        signing_keys=google_signing_keys(),
    )


def create_app(
    settings: Settings,
    email_sender: EmailSender | None = None,
    google: GoogleIdentityProvider | None = None,
) -> FastAPI:
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Warned at startup rather than in create_app so the OpenAPI export keeps a clean stdout.
        if settings.jwt_private_key is None:
            logger.warning(
                "jwt_signing_key_ephemeral", detail="Access tokens will not survive a restart."
            )
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
    private_key = signing_key(settings)
    app.state.access_tokens = AccessTokens(
        private_key, issuer=settings.jwt_issuer, audience=settings.jwt_audience
    )
    app.state.oidc_state = OidcStateCodec(
        private_key, issuer=settings.jwt_issuer, audience=f"{settings.jwt_audience}:oidc"
    )
    app.state.google = google or default_google_client(settings)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.add_exception_handler(UnauthorizedError, handle_unauthorized)
    app.add_exception_handler(InvalidRefreshTokenError, handle_invalid_refresh_token)
    app.add_exception_handler(PasswordHashingBusyError, handle_password_hashing_busy)
    app.add_exception_handler(OidcUnavailableError, handle_oidc_unavailable)
    register_rate_limiting(app)
    api_router = APIRouter(prefix=API_PREFIX)
    api_router.include_router(ops_router)
    api_router.include_router(auth_router)
    app.include_router(api_router)
    return app


def build_app() -> FastAPI:
    return create_app(Settings())
