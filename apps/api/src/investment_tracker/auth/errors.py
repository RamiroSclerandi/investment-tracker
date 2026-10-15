import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

from investment_tracker.core.errors import DomainError, problem_response

logger = structlog.get_logger()


class InvalidEmailTokenError(DomainError):
    code = "INVALID_EMAIL_TOKEN"
    status = 400
    title = "Invalid token"

    def __init__(self) -> None:
        super().__init__("The link is invalid or has expired.")


class InvalidCredentialsError(DomainError):
    code = "INVALID_CREDENTIALS"
    status = 401
    title = "Invalid credentials"

    def __init__(self) -> None:
        super().__init__("The email or password is incorrect.")


class EmailNotVerifiedError(DomainError):
    code = "EMAIL_NOT_VERIFIED"
    status = 403
    title = "Email not verified"

    def __init__(self) -> None:
        super().__init__("Verify your email before logging in.")


class InvalidRefreshTokenError(DomainError):
    code = "INVALID_REFRESH_TOKEN"
    status = 401
    title = "Invalid refresh token"

    def __init__(self) -> None:
        super().__init__("The session is invalid or has expired. Log in again.")


class CsrfHeaderRequiredError(DomainError):
    code = "CSRF_HEADER_REQUIRED"
    status = 403
    title = "CSRF header required"

    def __init__(self) -> None:
        super().__init__("The X-Requested-With header is missing or invalid.")


class PasswordHashingBusyError(DomainError):
    code = "SERVICE_BUSY"
    status = 503
    title = "Service busy"

    def __init__(self) -> None:
        super().__init__("The service is busy. Try again in a few seconds.")


async def handle_password_hashing_busy(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, PasswordHashingBusyError):
        raise exc
    logger.warning("argon2_capacity_exhausted")
    response = problem_response(
        request, status=exc.status, title=exc.title, detail=str(exc), code=exc.code
    )
    response.headers["Retry-After"] = "5"
    return response


class InvalidAccessTokenError(Exception):
    pass


class UnauthorizedError(DomainError):
    code = "UNAUTHORIZED"
    status = 401
    title = "Unauthorized"

    def __init__(self) -> None:
        super().__init__("A valid access token is required.")


async def handle_unauthorized(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, UnauthorizedError):
        raise exc
    response = problem_response(
        request, status=exc.status, title=exc.title, detail=str(exc), code=exc.code
    )
    response.headers["WWW-Authenticate"] = "Bearer"
    return response
