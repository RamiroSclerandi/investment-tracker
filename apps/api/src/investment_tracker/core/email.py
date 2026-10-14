import asyncio
import email.message
import smtplib
import ssl
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import unquote, urlsplit

DEFAULT_PORTS = {"smtp": 25, "smtp+starttls": 587, "smtps": 465}
SMTP_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str


class EmailDeliveryError(Exception):
    pass


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class SmtpEmailSender:
    def __init__(self, url: str, sender: str) -> None:
        parts = urlsplit(url)
        self._scheme = parts.scheme
        self._host = parts.hostname or "localhost"
        self._port = parts.port or DEFAULT_PORTS[parts.scheme]
        self._username = unquote(parts.username) if parts.username else None
        self._password = unquote(parts.password) if parts.password else None
        self._sender = sender

    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._send, message)

    def _send(self, message: EmailMessage) -> None:
        mime = email.message.EmailMessage()
        mime["From"] = self._sender
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        try:
            with self._connect() as client:
                if self._scheme == "smtp+starttls":
                    client.starttls(context=ssl.create_default_context())
                if self._username is not None:
                    client.login(self._username, self._password or "")
                client.send_message(mime)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError(f"SMTP delivery failed: {type(exc).__name__}") from None

    def _connect(self) -> smtplib.SMTP:
        if self._scheme == "smtps":
            return smtplib.SMTP_SSL(
                self._host,
                self._port,
                timeout=SMTP_TIMEOUT_SECONDS,
                context=ssl.create_default_context(),
            )
        return smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS)


class UnconfiguredEmailSender:
    async def send(self, message: EmailMessage) -> None:
        raise EmailDeliveryError("SMTP_URL is not configured.")
