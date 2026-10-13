import logging
import re
import sys
from typing import Any

import structlog
from structlog.typing import EventDict

REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"
SENSITIVE_KEY_PARTS = ("password", "token", "secret", "cookie", "authorization", "email")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _is_sensitive_key(key: object) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED if _is_sensitive_key(k) else _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return EMAIL_PATTERN.sub(REDACTED_EMAIL, value)
    return value


def redact_sensitive(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    redacted: EventDict = _redact_value(event_dict)
    return redacted


def configure_logging(level: str) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            redact_sensitive,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
