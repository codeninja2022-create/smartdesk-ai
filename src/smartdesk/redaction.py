"""Sensitive-data redaction for anything leaving the process (traces, logs).

Patterns are applied in order; secrets are matched before generic PII so a
token that happens to contain digits is labelled as a secret, not a phone number.
"""

import logging
import re
from collections.abc import Callable
from typing import Any

_MIN_PHONE_DIGITS = 10  # excludes dates (2026-10-30) and short IDs (ext. 2020)


def _redact_phone(match: re.Match[str]) -> str:
    digits = sum(ch.isdigit() for ch in match.group(0))
    return "[REDACTED_PHONE]" if digits >= _MIN_PHONE_DIGITS else match.group(0)


_PATTERNS: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    # Secrets
    (re.compile(r"\bsk-lf-[A-Za-z0-9-]{8,}"), "[REDACTED_LANGFUSE_KEY]"),
    (re.compile(r"\bpk-lf-[A-Za-z0-9-]{8,}"), "[REDACTED_LANGFUSE_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bATATT[A-Za-z0-9_=-]{20,}"), "[REDACTED_JIRA_TOKEN]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer [REDACTED_TOKEN]"),
    (
        re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token)\b(\s*[:=]\s*)\S+"),
        r"\1\2[REDACTED]",
    ),
    # PII
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_CARD_NUMBER]"),
    (re.compile(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)"), _redact_phone),
]


def redact_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact(data: Any) -> Any:
    """Recursively redact strings inside dicts, lists and tuples.

    Non-string leaves are returned unchanged, so the result stays JSON-serializable
    whenever the input was.
    """
    if isinstance(data, str):
        return redact_text(data)
    if isinstance(data, dict):
        return {key: redact(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return type(data)(redact(item) for item in data)
    return data


def langfuse_mask(*, data: Any, **_: Any) -> Any:
    """Adapter matching Langfuse's `MaskFunction` protocol."""
    return redact(data)


class RedactingFilter(logging.Filter):
    """Redacts the formatted message (and exception text) of every record a handler emits."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def install_log_redaction(*handlers: logging.Handler) -> None:
    """Attach `RedactingFilter` to these handlers (default: the root logger's handlers)."""
    for handler in handlers or tuple(logging.getLogger().handlers):
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
