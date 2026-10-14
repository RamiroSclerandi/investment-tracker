import uuid
from typing import Annotated, Literal, Self

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

from investment_tracker.auth.dependencies import (
    CurrentUserDep,
    SessionServiceDep,
    require_csrf_header,
)
from investment_tracker.auth.errors import InvalidRefreshTokenError
from investment_tracker.auth.models import Currency, User
from investment_tracker.auth.service import (
    REFRESH_TOKEN_TTL,
    AuthService,
    IssuedSession,
    ProfileService,
)
from investment_tracker.core.db import SessionDep
from investment_tracker.core.email import EmailDeliveryError, EmailMessage, EmailSender
from investment_tracker.core.errors import problem_response
from investment_tracker.core.rate_limit import client_ip, client_ip_key, limiter, login_limiter

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "it_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"
NO_STORE = {"Cache-Control": "no-store"}


Password = Annotated[str, Field(min_length=12, max_length=128)]
DisplayName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[^\x00-\x1f\x7f\x85\u2028\u2029]+$",
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
    request: Request,
    body: ResendVerificationRequest,
    service: AuthServiceDep,
    background_tasks: BackgroundTasks,
) -> AcceptedResponse:
    message = await service.resend_verification(body.email)
    schedule_delivery(request, background_tasks, message)
    return AcceptedResponse()


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    service: AuthServiceDep,
    background_tasks: BackgroundTasks,
) -> AcceptedResponse:
    message = await service.request_password_reset(body.email)
    schedule_delivery(request, background_tasks, message)
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
