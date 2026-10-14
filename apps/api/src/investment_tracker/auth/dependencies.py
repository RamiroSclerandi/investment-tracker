from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from investment_tracker.auth.errors import UnauthorizedError
from investment_tracker.auth.models import User
from investment_tracker.auth.service import SessionService
from investment_tracker.core.db import SessionDep

bearer_scheme = HTTPBearer(auto_error=False)


def get_session_service(request: Request, session: SessionDep) -> SessionService:
    return SessionService(session, request.app.state.access_tokens)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]


async def get_current_user(
    service: SessionServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise UnauthorizedError
    return await service.authenticate(credentials.credentials)


CurrentUserDep = Annotated[User, Depends(get_current_user)]
