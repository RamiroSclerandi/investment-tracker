import logging
import re
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, Processor

REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"
SENSITIVE_KEY_PARTS = (
    "password", "passwd", "pwd", "token", "secret", "cookie", "authorization", "email",
    "api_key", "apikey", "session", "jwt", "credential", "dsn", "database_url",
    "private_key", "code_verifier", "nonce", "otp",
)  # fmt: skip
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
KEY_VALUE_PATTERN = re.compile(
    r"\b([\w-]*(?:" + "|".join(SENSITIVE_KEY_PARTS) + r")[\w-]*)(['\"]?\s*[=:]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|(?:Bearer\s+|Basic\s+)?[^\s,;&)}\]]+)",
    re.IGNORECASE,
)
LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")
ACCESS_LOG_ARGS_COUNT = 5


def _is_sensitive_key(key: object) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _scrub_text(text: str) -> str:
    masked = KEY_VALUE_PATTERN.sub(lambda match: f"{match[1]}{match[2]}{REDACTED}", text)
    return EMAIL_PATTERN.sub(REDACTED_EMAIL, masked)


def _redact_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, dict):
        return {k: REDACTED if _is_sensitive_key(k) else _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_redact_value(item) for item in value]
    return _scrub_text(value if isinstance(value, str) else str(value))


def redact_sensitive(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    redacted: EventDict = _redact_value(event_dict)
    return redacted


class StripAccessLogQuery(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if (
            record.name == "uvicorn.access"
            and isinstance(args, tuple)
            and len(args) == ACCESS_LOG_ARGS_COUNT
            and isinstance(args[2], str)
        ):
            record.args = (*args[:2], args[2].partition("?")[0], *args[3:])
        return True


def configure_logging(level: str) -> None:
    numeric_level = logging.getLevelNamesMapping()[level]
    shared_processors: list[Processor] = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        redact_sensitive,
    ]
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(StripAccessLogQuery())
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors[:3],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                redact_sensitive,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric_level)
    for name in LOGGER_NAMES:
        named = logging.getLogger(name)
        named.handlers = []
        named.propagate = True
