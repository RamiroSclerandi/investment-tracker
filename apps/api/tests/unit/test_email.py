import smtplib
from typing import Any, ClassVar

import pytest

from investment_tracker.core.email import (
    EmailDeliveryError,
    EmailMessage,
    SmtpEmailSender,
    UnconfiguredEmailSender,
)

MESSAGE = EmailMessage(to="ana@example.com", subject="Hola", text="Cuerpo")


class FakeSmtp:
    instances: ClassVar[list[FakeSmtp]] = []

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.host, self.port, self.kwargs = host, port, kwargs
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.sent: list[Any] = []
        FakeSmtp.instances.append(self)

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self, **kwargs: Any) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, message: Any) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSmtp.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)


async def test_plain_smtp_sends_without_tls_or_login() -> None:
    await SmtpEmailSender("smtp://mailpit:1025", "App <no-reply@example.com>").send(MESSAGE)

    client = FakeSmtp.instances[0]
    assert (client.host, client.port) == ("mailpit", 1025)
    assert not client.started_tls
    assert client.login_args is None
    sent = client.sent[0]
    assert sent["To"] == "ana@example.com"
    assert sent["From"] == "App <no-reply@example.com>"
    assert sent["Subject"] == "Hola"


async def test_starttls_upgrades_and_logs_in_with_decoded_credentials() -> None:
    sender = SmtpEmailSender("smtp+starttls://api%40key:p%40ss@smtp.example.com:587", "App <a@b.c>")

    await sender.send(MESSAGE)

    client = FakeSmtp.instances[0]
    assert client.started_tls
    assert client.login_args == ("api@key", "p@ss")


async def test_smtps_uses_implicit_tls_on_port_465_by_default() -> None:
    await SmtpEmailSender("smtps://u:p@smtp.example.com", "App <a@b.c>").send(MESSAGE)

    client = FakeSmtp.instances[0]
    assert client.port == 465
    assert "context" in client.kwargs


async def test_transport_errors_become_email_delivery_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError

    monkeypatch.setattr(smtplib, "SMTP", refuse)

    with pytest.raises(EmailDeliveryError):
        await SmtpEmailSender("smtp://mailpit:1025", "App <a@b.c>").send(MESSAGE)


async def test_unconfigured_sender_always_fails() -> None:
    with pytest.raises(EmailDeliveryError, match="SMTP_URL is not configured"):
        await UnconfiguredEmailSender().send(MESSAGE)
