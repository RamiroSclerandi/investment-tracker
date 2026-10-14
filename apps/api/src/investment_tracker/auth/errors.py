from investment_tracker.core.errors import DomainError


class InvalidEmailTokenError(DomainError):
    code = "INVALID_EMAIL_TOKEN"
    status = 400
    title = "Invalid token"

    def __init__(self) -> None:
        super().__init__("The link is invalid or has expired.")
