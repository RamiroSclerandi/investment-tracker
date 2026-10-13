from structlog.typing import EventDict

from investment_tracker.core.logging import redact_sensitive


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
