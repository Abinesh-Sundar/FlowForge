"""Redaction of sensitive values before anything is stored in a trace or sent to a model."""
from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|authorization|bank_?account|iban|account_?number|card|ssn|credential)",
    re.I,
)
# Metrics, not secrets: token *counts* and timing fields must survive redaction.
METRIC_KEYS = {"input_tokens", "output_tokens", "total_tokens", "max_tokens", "cache_read_input_tokens",
               "cache_creation_input_tokens"}
VALUE_PATTERNS = [
    (re.compile(r"sk-(?:ant-|proj-|or-v1-)?[A-Za-z0-9_\-]{10,}"), "[REDACTED_KEY]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"), "[REDACTED_IBAN]"),
]
MAX_STR = 4000
REDACTED = "[REDACTED]"


def redact_string(s: str) -> str:
    for pat, repl in VALUE_PATTERNS:
        s = pat.sub(repl, s)
    if len(s) > MAX_STR:
        s = s[:MAX_STR] + f"… [truncated {len(s) - MAX_STR} chars]"
    return s


def redact(obj: Any) -> Any:
    """Return a deep copy of obj with sensitive keys/values masked."""
    if isinstance(obj, dict):
        return {
            k: (REDACTED if isinstance(k, str) and k not in METRIC_KEYS and SENSITIVE_KEY.search(k)
                else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return redact_string(obj)
    return obj
