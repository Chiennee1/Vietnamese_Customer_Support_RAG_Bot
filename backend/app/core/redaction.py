import re
from collections.abc import Mapping, MutableMapping
from typing import Any

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.-]?\d){9,10}(?!\d)")
BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{10,}\b", re.IGNORECASE)
OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[\s-]?){13,19}(?!\d)")
SENSITIVE_KEYS = {
    "authorization",
    "password",
    "password_hash",
    "access_token",
    "refresh_token",
    "api_key",
    "jwt_secret",
    "database_url",
    "prompt",
    "message",
    "content",
}


def redact_text(value: str) -> str:
    redacted = EMAIL_PATTERN.sub("[EMAIL_REDACTED]", value)
    redacted = PHONE_PATTERN.sub("[PHONE_REDACTED]", redacted)
    redacted = BEARER_PATTERN.sub("Bearer [TOKEN_REDACTED]", redacted)
    redacted = OPENAI_KEY_PATTERN.sub("[API_KEY_REDACTED]", redacted)
    return CARD_PATTERN.sub("[CARD_REDACTED]", redacted)


def redact_value(value: Any, *, key: str | None = None) -> Any:
    if key and key.casefold() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            str(child_key): redact_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def structlog_redactor(
    _: Any,
    __: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    return {key: redact_value(value, key=key) for key, value in event_dict.items()}
