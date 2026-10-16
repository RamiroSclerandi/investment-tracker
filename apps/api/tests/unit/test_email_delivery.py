import structlog

from investment_tracker.auth.router import deliver_email
from investment_tracker.core.email import EmailDeliveryError, EmailMessage

MESSAGE = EmailMessage(to="ana@example.com", subject="Verify your email", text="Hello Ana")


class FailingSender:
    async def send(self, message: EmailMessage) -> None:
        # The message carries the recipient and a token-shaped fragment on purpose.
        raise EmailDeliveryError("SMTP delivery failed: verify token=abc123 to ana@example.com")


async def test_a_failed_delivery_logs_the_exception_type_and_nothing_else() -> None:
    with structlog.testing.capture_logs() as logs:
        await deliver_email(FailingSender(), MESSAGE)

    assert logs == [
        {
            "event": "email_delivery_failed",
            "error_type": "EmailDeliveryError",
            "log_level": "warning",
        }
    ]
