import json
import logging
from typing import Any

import pytest
import structlog
from structlog.typing import EventDict

from investment_tracker.core.logging import configure_logging, redact_sensitive


def redact(event_dict: EventDict) -> EventDict:
    return redact_sensitive(None, "info", event_dict)


def test_sensitive_keys_are_redacted_recursively() -> None:
    result = redact(
        {
            "event": "login",
            "password": "hunter2",
            "Access_Token": "abc",
            "headers": {"Authorization": "Bearer x", "Set-Cookie": "sid=1", "accept": "json"},
            "users": [{"email": "a@b.com", "name": "ana"}],
            "refresh_token_hash": "zzz",
        }
    )

    assert result["password"] == "[REDACTED]"
    assert result["Access_Token"] == "[REDACTED]"
    assert result["headers"] == {
        "Authorization": "[REDACTED]",
        "Set-Cookie": "[REDACTED]",
        "accept": "json",
    }
    assert result["users"] == [{"email": "[REDACTED]", "name": "ana"}]
    assert result["refresh_token_hash"] == "[REDACTED]"


def test_email_inside_free_text_is_masked() -> None:
    result = redact({"event": "sent mail to jane.doe+x@example.com now", "note": ["a@b.io"]})

    assert result["event"] == "sent mail to [REDACTED_EMAIL] now"
    assert result["note"] == ["[REDACTED_EMAIL]"]


def test_non_sensitive_values_are_untouched() -> None:
    event = {"event": "ok", "count": 3, "ratio": 0.5, "flag": True, "none": None, "path": "/x"}

    assert redact(dict(event)) == event


def test_new_sensitive_keys_are_redacted() -> None:
    keys = [
        "api_key", "apikey", "passwd", "pwd", "session_id", "jwt", "credential",
        "dsn", "database_url", "private_key", "code_verifier", "nonce", "otp",
    ]  # fmt: skip
    result = redact({"event": "x", **{key: "value" for key in keys}})

    assert all(result[key] == "[REDACTED]" for key in keys)


def test_key_value_pairs_inside_free_text_are_redacted() -> None:
    result = redact(
        {"event": "login failed password=hunter2 and token: abc123 for user", "other": "ok=1"}
    )

    assert "hunter2" not in result["event"]
    assert "abc123" not in result["event"]
    assert result["event"].startswith("login failed password=[REDACTED]")
    assert result["other"] == "ok=1"


def test_bare_jwt_inside_free_text_is_redacted() -> None:
    jwt = "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"

    result = redact({"event": f"decode failed for {jwt} at edge", "path": "/a.b.c"})

    assert result["event"] == "decode failed for [REDACTED] at edge"
    assert result["path"] == "/a.b.c"


def test_postgres_key_detail_masks_sensitive_columns_only() -> None:
    result = redact(
        {
            "event": "DETAIL:  Key (token_hash)=(9f86d0) already exists.",
            "unique": "Key (provider, provider_subject)=(google, 123) already exists.",
            "mixed": "Key (provider, email)=(google, a@b.com) already exists.",
            "contact": "Key (contact)=(a@b.com) already exists.",
        }
    )

    assert result["event"] == "DETAIL:  Key (token_hash)=([REDACTED]) already exists."
    assert result["unique"] == "Key (provider, provider_subject)=(google, 123) already exists."
    assert result["mixed"] == "Key (provider, email)=([REDACTED]) already exists."
    assert result["contact"] == "Key (contact)=([REDACTED_EMAIL]) already exists."


def test_postgres_failing_row_detail_is_redacted() -> None:
    detail = (
        'null value in column "email" violates not-null constraint\n'
        "DETAIL:  Failing row contains (1, $argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA, null).\n"
        "next line"
    )

    result = redact({"event": detail})

    assert "argon2id" not in result["event"]
    assert "DETAIL:  Failing row contains ([REDACTED]).\nnext line" in result["event"]


def test_quoted_postgres_key_detail_is_redacted() -> None:
    result = redact({"event": "IntegrityError('Key (token_hash)=(abc)')", "list": "[(token)=(x)]"})

    assert result["event"] == "IntegrityError('Key (token_hash)=([REDACTED])')"
    assert result["list"] == "[(token)=([REDACTED])]"


def test_non_primitive_values_are_coerced_and_scrubbed() -> None:
    result = redact(
        {
            "error": ValueError("bad user a@b.com"),
            "tags": {"x@y.com", "plain"},
            "raw": b"token=abc",
        }
    )

    assert result["error"] == "bad user [REDACTED_EMAIL]"
    assert "a@b.com" not in str(result["tags"])
    assert "abc" not in str(result["raw"])
    assert isinstance(result["tags"], list)


def configured_output(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    lines = capsys.readouterr().out.strip().splitlines()
    return [json.loads(line) for line in lines]


def test_exception_value_and_set_are_masked_in_json_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")

    structlog.get_logger().info("evt", error=ValueError("bad a@b.com"), tags={"c@d.com"})

    record = configured_output(capsys)[0]
    assert "a@b.com" not in json.dumps(record)
    assert "c@d.com" not in json.dumps(record)


def test_traceback_text_is_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")

    try:
        raise RuntimeError("connect failed password=hunter2 owner a@b.com")
    except RuntimeError as exc:
        structlog.get_logger().error("boom", exc_info=exc)

    record = configured_output(capsys)[0]
    assert "Traceback" in record["exception"]
    assert "hunter2" not in record["exception"]
    assert "a@b.com" not in record["exception"]


def test_stdlib_loggers_are_redacted_and_rendered_as_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")

    logging.getLogger("uvicorn.error").error("failure for a@b.com token=abc")

    record = configured_output(capsys)[0]
    assert record["event"] == "failure for [REDACTED_EMAIL] token=[REDACTED]"
    assert record["level"] == "error"


def test_stdlib_exception_traceback_is_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")

    try:
        raise RuntimeError("oops password=hunter2")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")

    record = configured_output(capsys)[0]
    assert "hunter2" not in json.dumps(record)


def test_access_log_drops_query_string(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/path?q=zzz", "1.1", 200
    )

    record = configured_output(capsys)[0]
    assert '"GET /path HTTP/1.1" 200' in record["event"]
    assert "zzz" not in record["event"]
