import uuid
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, StringConstraints

from investment_tracker.auth.dependencies import CurrentUserDep, SessionServiceDep
from investment_tracker.auth.models import Currency
from investment_tracker.auth.service import REFRESH_TOKEN_TTL, AuthService
from investment_tracker.core.db import SessionDep
from investment_tracker.core.email import EmailDeliveryError, EmailMessage, EmailSender
from investment_tracker.core.rate_limit import client_ip, client_ip_key, limiter, login_limiter

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "it_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"
NO_STORE = {"Cache-Control": "no-store"}


Password = Annotated[str, Field(min_length=12, max_length=128)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    display_name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=80,
            pattern=r"^[^\x00-\x1f\x7f\x85\u2028\u2029]+$",
        ),
    ]


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    password: Password


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    # No minimum beyond one character, so a validation error never reveals the password policy.
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


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


@router.post("/login")
@limiter.limit("20/minute")
async def login(
    request: Request, response: Response, body: LoginRequest, service: SessionServiceDep
) -> TokenResponse:
    response.headers.update(NO_STORE)
    login_limiter.hit(f"{client_ip_key(request)}:{body.email.lower()}")
    address = client_ip(request)
    issued = await service.login(
        body.email,
        body.password,
        user_agent=request.headers.get("user-agent"),
        ip=str(address) if address is not None else None,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        issued.refresh_token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.get("/me")
async def me(response: Response, user: CurrentUserDep) -> ProfileResponse:
    response.headers.update(NO_STORE)
    return ProfileResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        preferred_currency=user.preferred_currency,
        email_verified=user.email_verified_at is not None,
    )
