import asyncio
import base64
import math
import re
import time
from collections.abc import Callable
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr
from typing import TypeIs

import httpx
from pydantic import SecretStr

from investment_tracker.core.email import EmailDeliveryError, EmailMessage

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_HTTP_TIMEOUT_SECONDS = 10.0
TOKEN_EXPIRY_MARGIN_SECONDS = 60.0
# Only Google's short OAuth error code may reach the message; descriptions can echo request data.
SAFE_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


class GmailApiEmailSender:
    def __init__(
        self,
        client_id: str,
        client_secret: SecretStr,
        refresh_token: SecretStr,
        *,
        sender: str,
        display_name: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._from = formataddr((display_name, sender)) if display_name else sender
        self._transport = transport
        self._clock = clock
        self._lock = asyncio.Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0

    async def send(self, message: EmailMessage) -> None:
        raw = self._encode(message)
        async with httpx.AsyncClient(
            transport=self._transport, timeout=GMAIL_HTTP_TIMEOUT_SECONDS
        ) as client:
            token = await self._get_access_token(client)
            response = await self._post_message(client, token, raw)
            if response.status_code == 401:
                self._drop_access_token(token)
                token = await self._get_access_token(client)
                response = await self._post_message(client, token, raw)
        if not response.is_success:
            raise EmailDeliveryError(f"gmail_send_failed: {response.status_code}")

    def _encode(self, message: EmailMessage) -> str:
        mime = MimeMessage()
        mime["From"] = self._from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        return base64.urlsafe_b64encode(mime.as_bytes()).decode()

    async def _post_message(
        self, client: httpx.AsyncClient, token: str, raw: str
    ) -> httpx.Response:
        try:
            return await client.post(
                GMAIL_SEND_URL, headers={"Authorization": f"Bearer {token}"}, json={"raw": raw}
            )
        except httpx.HTTPError as exc:
            raise EmailDeliveryError(f"gmail_send_failed: {type(exc).__name__}") from None

    def _drop_access_token(self, token: str) -> None:
        # A concurrent send may already have replaced the rejected token with a fresh one.
        if self._access_token == token:
            self._access_token = None

    async def _get_access_token(self, client: httpx.AsyncClient) -> str:
        async with self._lock:
            if self._access_token is not None and self._clock() < self._expires_at:
                return self._access_token
            token, expires_in = await self._refresh_access_token(client)
            self._access_token = token
            self._expires_at = self._clock() + expires_in - TOKEN_EXPIRY_MARGIN_SECONDS
            return token

    async def _refresh_access_token(self, client: httpx.AsyncClient) -> tuple[str, float]:
        form = {
            "client_id": self._client_id,
            "client_secret": self._client_secret.get_secret_value(),
            "refresh_token": self._refresh_token.get_secret_value(),
            "grant_type": "refresh_token",
        }
        try:
            response = await client.post(GMAIL_TOKEN_URL, data=form)
        except httpx.HTTPError as exc:
            raise EmailDeliveryError(f"gmail_token_refresh_failed: {type(exc).__name__}") from None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise EmailDeliveryError(f"gmail_token_refresh_failed: {response.status_code}")
        token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if (
            response.is_success
            and isinstance(token, str)
            and token
            and _is_positive_finite(expires_in)
        ):
            return token, float(expires_in)
        raise EmailDeliveryError(f"gmail_token_refresh_failed: {_error_code(payload, response)}")


def _is_positive_finite(value: object) -> TypeIs[int | float]:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _error_code(payload: dict[str, object], response: httpx.Response) -> str:
    error = payload.get("error")
    if isinstance(error, str) and SAFE_ERROR_CODE.fullmatch(error):
        return error
    return "malformed_response" if response.is_success else str(response.status_code)
