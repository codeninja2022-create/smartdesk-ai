import json

import pytest

from smartdesk.redaction import langfuse_mask, redact, redact_text


@pytest.mark.parametrize(
    ("text", "secret", "label"),
    [
        ("key sk-proj-AbCdEf1234567890GhIjKlMn", "sk-proj-AbCdEf1234567890GhIjKlMn", "[REDACTED_API_KEY]"),
        ("lf sk-lf-1234abcd-5678", "sk-lf-1234abcd-5678", "[REDACTED_LANGFUSE_KEY]"),
        ("jira ATATT3xFfGF0abcdefghijklmnop12345", "ATATT3xFfGF0abcdefghijklmnop12345", "[REDACTED_JIRA_TOKEN]"),
        ("Authorization: Bearer abcdefghijklmnop.qrstuv", "abcdefghijklmnop.qrstuv", "Bearer [REDACTED_TOKEN]"),
        ("my password: Hunter2!", "Hunter2!", "password: [REDACTED]"),
        ("mail jane.doe@novatech.com now", "jane.doe@novatech.com", "[REDACTED_EMAIL]"),
        ("call +91 98765 43210 please", "98765 43210", "[REDACTED_PHONE]"),
        ("card 4111 1111 1111 1111", "4111 1111 1111 1111", "[REDACTED_CARD_NUMBER]"),
    ],
)
def test_redacts_secrets_and_pii(text, secret, label):
    result = redact_text(text)
    assert secret not in result
    assert label in result


@pytest.mark.parametrize(
    "text",
    [
        "How many sick leaves do I get per year?",
        "Ticket IT-2847 was updated on 2026-10-30.",
        "Contact IT at ext. 2020.",
        "Casual leave is 12 days/year.",
    ],
)
def test_leaves_ordinary_text_unchanged(text):
    assert redact_text(text) == text


def test_redacts_nested_structures_and_keeps_types():
    data = {
        "messages": [{"role": "user", "content": "I'm bob@novatech.com"}],
        "meta": ("token=abc123", 42, None, True),
    }
    result = redact(data)
    assert result == {
        "messages": [{"role": "user", "content": "I'm [REDACTED_EMAIL]"}],
        "meta": ("token=[REDACTED]", 42, None, True),
    }
    json.dumps(result)  # still serializable


def test_langfuse_mask_adapter():
    assert langfuse_mask(data="sk-abcdefghijklmnopqrstuvwxyz") == "[REDACTED_API_KEY]"
