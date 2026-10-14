from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field, StringConstraints

from investment_tracker.auth.service import AuthService
from investment_tracker.core.db import SessionDep
from investment_tracker.core.email import EmailDeliveryError, EmailMessage, EmailSender
from investment_tracker.core.rate_limit import limiter

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
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


class ResendVerificationRequest(BaseModel):
    email: EmailStr


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
async def verify_email(body: VerifyEmailRequest, service: AuthServiceDep) -> VerifiedResponse:
    await service.verify_email(body.token)
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
