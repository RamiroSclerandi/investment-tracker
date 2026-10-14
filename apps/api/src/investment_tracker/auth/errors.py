from fastapi import Request
from fastapi.responses import JSONResponse

from investment_tracker.core.errors import DomainError, problem_response


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
