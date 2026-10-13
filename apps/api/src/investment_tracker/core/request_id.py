import re
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER_NAME = "X-Request-ID"
VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def resolve_request_id(incoming: str | None) -> str:
    if incoming is not None and VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return str(uuid.uuid4())


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = dict(scope["headers"]).get(HEADER_NAME.lower().encode())
        request_id = resolve_request_id(raw.decode("latin-1") if raw is not None else None)
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[HEADER_NAME] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
