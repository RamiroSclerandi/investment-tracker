from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from investment_tracker.auth.errors import CsrfHeaderRequiredError, UnauthorizedError
from investment_tracker.auth.models import User
from investment_tracker.auth.service import SessionService
from investment_tracker.core.db import SessionDep, set_session_user

bearer_scheme = HTTPBearer(auto_error=False)

CSRF_HEADER_VALUE = "investment-tracker"


def get_session_service(request: Request, session: SessionDep) -> SessionService:
    return SessionService(session, request.app.state.access_tokens)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]


async def get_current_user(
    service: SessionServiceDep,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise UnauthorizedError
    user = await service.authenticate(credentials.credentials)
    set_session_user(session, user.id)
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


# A cross-site form or link cannot set a custom header, so its presence proves a same-origin call.
async def require_csrf_header(
    x_requested_with: Annotated[str | None, Header()] = None,
) -> None:
    if x_requested_with != CSRF_HEADER_VALUE:
        raise CsrfHeaderRequiredError
