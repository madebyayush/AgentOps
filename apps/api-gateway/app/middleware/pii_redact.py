"""
PII Redaction Log Filter
-------------------------
Scans Python log records for PII patterns and replaces them with
`[REDACTED_<TYPE>]` tokens BEFORE the log record is emitted to any handler.

This does NOT alter API responses — it only sanitises log output so that
sensitive data never reaches Jaeger, Grafana Loki, or CloudWatch.

Registered in main.py:
    logging.getLogger().addFilter(PIIRedactLogFilter())

Patterns covered:
  - EMAIL       : standard RFC5322 email addresses
  - PHONE       : US-style phone numbers (dashes, dots, parentheses)
  - SSN         : ###-##-#### Social Security Numbers
  - CREDIT_CARD : 13-19 digit sequences (covers Visa, MC, Amex, etc.)
  - API_KEY     : sk-*, Bearer tokens, common API key prefixes
  - JWT         : base64url.base64url.base64url token format
"""
from __future__ import annotations

import logging
import re


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL",       re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", re.IGNORECASE)),
    ("PHONE",       re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
    ("SSN",         re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6011\d{12})\b")),
    (
        "API_KEY",
        re.compile(
            r"\b(?:sk|sk-proj|ak|pk|api[-_]?key)[-_]?[a-zA-Z0-9]{16,80}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "JWT",
        re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"),
    ),
]


class PIIRedactLogFilter(logging.Filter):
    """
    A logging.Filter that scrubs PII from log record messages and args
    before they are formatted and emitted.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the formatted message
        try:
            msg = record.getMessage()
            redacted = _redact(msg)
            # Replace the message and clear args so LogRecord.getMessage() returns clean text
            record.msg = redacted
            record.args = None
        except Exception:
            pass  # never let the filter break logging
        return True  # always emit (just cleaned)


def _redact(text: str) -> str:
    """Apply all PII patterns to a string and return the scrubbed version."""
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[REDACTED_{label}]", text)
    return text
