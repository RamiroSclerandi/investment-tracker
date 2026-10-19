import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal, Self

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

from investment_tracker.auth.cookies import OIDC_COOKIE_NAME, OIDC_COOKIE_PATH
from investment_tracker.auth.dependencies import (
    CurrentUserDep,
    SessionServiceDep,
    require_csrf_header,
)
from investment_tracker.auth.display_name import DISPLAY_NAME_MAX_LENGTH, DISPLAY_NAME_PATTERN
from investment_tracker.auth.errors import InvalidRefreshTokenError, OidcUnavailableError
from investment_tracker.auth.google import GoogleIdentityProvider, GoogleSignInError
from investment_tracker.auth.models import Currency, User
from investment_tracker.auth.service import (
    REFRESH_TOKEN_TTL,
    AuthService,
    GoogleSignInService,
    IssuedSession,
    ProfileService,
    start_google_sign_in,
)
from investment_tracker.core.db import SessionDep
from investment_tracker.core.email import EmailDeliveryError, EmailMessage, EmailSender
from investment_tracker.core.errors import problem_response
from investment_tracker.core.rate_limit import (
    client_ip,
    client_ip_key,
    forgot_email_limiter,
    handle_rate_limit_exceeded,
    limiter,
    login_limiter,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "it_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"
NO_STORE = {"Cache-Control": "no-store"}
OIDC_COOKIE_MAX_AGE_SECONDS = 600


Password = Annotated[str, Field(min_length=12, max_length=128)]
DisplayName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=DISPLAY_NAME_MAX_LENGTH,
        pattern=DISPLAY_NAME_PATTERN,
    ),
]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    display_name: DisplayName


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    password: Password


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    password: Password


class LoginRequest(BaseModel):
    # No minimum beyond one character, so a validation error never reveals the password policy.
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None = None
    preferred_currency: Currency | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> Self:
        if self.display_name is None and self.preferred_currency is None:
            raise ValueError("Provide display_name or preferred_currency.")
        return self


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105
    expires_in: int


class ProfileResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    preferred_currency: Currency
    email_verified: bool


class AcceptedResponse(BaseModel):
    status: Literal["accepted"] = "accepted"


class VerifiedResponse(BaseModel):
    status: Literal["verified"] = "verified"


def get_auth_service(request: Request, session: SessionDep) -> AuthService:
    return AuthService(session, request.app.state.settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_profile_service(session: SessionDep) -> ProfileService:
    return ProfileService(session)


ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


def get_google(request: Request) -> GoogleIdentityProvider:
    google: GoogleIdentityProvider | None = request.app.state.google
    if google is None:
        raise OidcUnavailableError
    return google


GoogleDep = Annotated[GoogleIdentityProvider, Depends(get_google)]


# The Google dependency comes first so an unconfigured app answers 503 before opening a session.
def get_google_sign_in_service(
    request: Request, google: GoogleDep, session: SessionDep
) -> GoogleSignInService:
    return GoogleSignInService(session, google, request.app.state.oidc_state)


GoogleSignInServiceDep = Annotated[GoogleSignInService, Depends(get_google_sign_in_service)]


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_oidc_cookie(response: Response) -> None:
    response.delete_cookie(
        OIDC_COOKIE_NAME, path=OIDC_COOKIE_PATH, secure=True, httponly=True, samesite="lax"
    )


def client_details(request: Request) -> tuple[str | None, str | None]:
    address = client_ip(request)
    return request.headers.get("user-agent"), str(address) if address is not None else None


def token_response(response: Response, issued: IssuedSession) -> TokenResponse:
    set_refresh_cookie(response, issued.refresh_token)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


def profile_response(response: Response, user: User) -> ProfileResponse:
    response.headers.update(NO_STORE)
    return ProfileResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        preferred_currency=user.preferred_currency,
        email_verified=user.email_verified_at is not None,
    )


def empty_response_clearing_cookie() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers=NO_STORE)
    clear_refresh_cookie(response)
    return response


async def handle_invalid_refresh_token(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, InvalidRefreshTokenError):
        raise exc
    response = problem_response(
        request, status=exc.status, title=exc.title, detail=str(exc), code=exc.code
    )
    response.headers.update(NO_STORE)
    clear_refresh_cookie(response)
    return response


async def deliver_email(sender: EmailSender, message: EmailMessage) -> None:
    try:
        await sender.send(message)
    except EmailDeliveryError as exc:
        logger.warning("email_delivery_failed", error_type=type(exc).__name__)


def schedule_delivery(
    request: Request, background_tasks: BackgroundTasks, message: EmailMessage | None
) -> None:
    # Delivery runs after the response so its latency cannot reveal whether an account exists.
    if message is not None:
        background_tasks.add_task(deliver_email, request.app.state.email_sender, message)


async def issue_account_email(
    request: Request,
    issue: Callable[[AuthService, str], Awaitable[EmailMessage | None]],
    email: str,
) -> None:
    # After the response, so timing cannot reveal an account; the request session is closed by then.
    state = request.app.state
    try:
        async with state.sessionmaker() as session:
            message = await issue(AuthService(session, state.settings), email)
    # Top-level task boundary: an escaped error would print its message in a traceback.
    except Exception as exc:
        logger.warning("account_email_task_failed", error_type=type(exc).__name__)
        return
    if message is not None:
        await deliver_email(state.email_sender, message)


# The cookie path constant is the mounted prefix of both Google routes.
OIDC_ROUTE_PATHS = (f"{OIDC_COOKIE_PATH}/start", f"{OIDC_COOKIE_PATH}/callback")


async def handle_rate_limit_exceeded_clearing_oidc_cookie(
    request: Request, exc: Exception
) -> JSONResponse:
    response = await handle_rate_limit_exceeded(request, exc)
    # The Google state cookie is single-use, so a 429 must not leave it behind for a retry.
    if request.url.path in OIDC_ROUTE_PATHS:
        clear_oidc_cookie(response)
    return response


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    service: AuthServiceDep,
    background_tasks: BackgroundTasks,
) -> AcceptedResponse:
    message = await service.register(body.email, body.password, body.display_name)
    schedule_delivery(request, background_tasks, message)
    return AcceptedResponse()


@router.post("/verify-email")
@limiter.limit("10/minute")
async def verify_email(
    request: Request, body: VerifyEmailRequest, service: AuthServiceDep
) -> VerifiedResponse:
    await service.verify_email(body.token, body.password)
    return VerifiedResponse()


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request, body: ResendVerificationRequest, background_tasks: BackgroundTasks
) -> AcceptedResponse:
    background_tasks.add_task(
        issue_account_email, request, AuthService.resend_verification, body.email
    )
    return AcceptedResponse()


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request, body: ForgotPasswordRequest, background_tasks: BackgroundTasks
) -> AcceptedResponse:
    if not forgot_email_limiter.allow(f"forgot:{body.email.lower()}"):
        # Dropped silently: a 429 or a delay here would reveal which addresses hit the cap.
        return AcceptedResponse()
    background_tasks.add_task(
        issue_account_email, request, AuthService.request_password_reset, body.email
    )
    return AcceptedResponse()


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def reset_password(
    request: Request, body: ResetPasswordRequest, service: AuthServiceDep
) -> Response:
    await service.reset_password(body.token, body.password)
    return empty_response_clearing_cookie()


@router.post("/login")
@limiter.limit("20/minute")
async def login(
    request: Request, response: Response, body: LoginRequest, service: SessionServiceDep
) -> TokenResponse:
    response.headers.update(NO_STORE)
    login_limiter.hit(f"{client_ip_key(request)}:{body.email.lower()}")
    user_agent, ip = client_details(request)
    issued = await service.login(body.email, body.password, user_agent=user_agent, ip=ip)
    return token_response(response, issued)


@router.post("/refresh", dependencies=[Depends(require_csrf_header)])
@limiter.limit("30/minute")
async def refresh(
    request: Request, response: Response, service: SessionServiceDep
) -> TokenResponse:
    response.headers.update(NO_STORE)
    user_agent, ip = client_details(request)
    issued = await service.refresh(
        request.cookies.get(REFRESH_COOKIE_NAME), user_agent=user_agent, ip=ip
    )
    return token_response(response, issued)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf_header)],
)
async def logout(request: Request, service: SessionServiceDep) -> Response:
    await service.logout(request.cookies.get(REFRESH_COOKIE_NAME))
    return empty_response_clearing_cookie()


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: CurrentUserDep, service: SessionServiceDep) -> Response:
    await service.logout_all(user.id)
    return empty_response_clearing_cookie()


def oidc_redirect(location: str) -> RedirectResponse:
    response = RedirectResponse(location, status_code=status.HTTP_302_FOUND, headers=NO_STORE)
    clear_oidc_cookie(response)
    return response


@router.get("/google/start", response_class=RedirectResponse, status_code=status.HTTP_302_FOUND)
@limiter.limit("10/minute")
async def google_start(request: Request, google: GoogleDep) -> RedirectResponse:
    authorization_url, cookie = start_google_sign_in(google, request.app.state.oidc_state)
    response = RedirectResponse(
        authorization_url, status_code=status.HTTP_302_FOUND, headers=NO_STORE
    )
    # Lax, not Strict: Google returns through a cross-site top-level navigation.
    response.set_cookie(
        OIDC_COOKIE_NAME,
        cookie,
        max_age=OIDC_COOKIE_MAX_AGE_SECONDS,
        path=OIDC_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/google/callback", response_class=RedirectResponse, status_code=status.HTTP_302_FOUND)
@limiter.limit("10/minute")
async def google_callback(
    request: Request,
    service: GoogleSignInServiceDep,
    background_tasks: BackgroundTasks,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    complete_url = f"{request.app.state.settings.web_base_url}/auth/complete"
    user_agent, ip = client_details(request)
    try:
        refresh_token, notification = await service.complete(
            cookie=request.cookies.get(OIDC_COOKIE_NAME),
            state=state,
            code=code,
            error=error,
            user_agent=user_agent,
            ip=ip,
        )
    except GoogleSignInError as exc:
        logger.warning("google_sign_in_failed", reason=exc.reason)
        return oidc_redirect(f"{complete_url}#error=oauth_failed")
    response = oidc_redirect(complete_url)
    set_refresh_cookie(response, refresh_token)
    schedule_delivery(request, background_tasks, notification)
    return response


@router.get("/me")
async def me(response: Response, user: CurrentUserDep) -> ProfileResponse:
    return profile_response(response, user)


@router.patch("/me")
async def update_me(
    response: Response,
    body: UpdateProfileRequest,
    user: CurrentUserDep,
    service: ProfileServiceDep,
) -> ProfileResponse:
    updated = await service.update(
        user.id, display_name=body.display_name, preferred_currency=body.preferred_currency
    )
    return profile_response(response, updated)
