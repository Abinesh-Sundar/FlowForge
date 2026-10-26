"""Deterministic fault injection shared by WhatIf scenarios and the Failure Simulator node."""
from __future__ import annotations

import copy
import json
from typing import Any

from .errors import NodeError

FAULT_KINDS = [
    "missing_field", "malformed_json", "wrong_type", "wrong_value",
    "http_500", "timeout", "empty_response", "fail_validation",
]
DATA_FAULTS = {"missing_field", "wrong_type", "wrong_value"}
RAW_FAULTS = {"malformed_json", "empty_response"}  # applied to LLM raw text before JSON parsing


def truncate_json(value: Any) -> str:
    text = json.dumps(value, indent=2) if not isinstance(value, str) else value
    return text[: max(8, int(len(text) * 0.6))]  # deterministic cut mid-document


def apply_raw(kind: str, raw: str) -> tuple[str, str]:
    if kind == "malformed_json":
        return truncate_json(raw), "Raw model text truncated mid-document (malformed JSON)"
    if kind == "empty_response":
        return "", "Raw model text replaced with an empty string"
    return raw, ""


def apply_data(kind: str, data: Any, field: str | None) -> tuple[Any, str | None]:
    """Mutate a dict payload. Returns (new_data, description) — description None means the fault was a no-op."""
    if not isinstance(data, dict):
        return data, None
    out = copy.deepcopy(data)
    if not field or field not in out:
        return data, None
    v = out[field]
    if kind == "missing_field":
        del out[field]
        return out, f"Removed field '{field}'"
    if kind == "wrong_type":
        if isinstance(v, bool):
            out[field] = "true" if v else "false"
        elif isinstance(v, (int, float)):
            out[field] = str(v)
        elif isinstance(v, str):
            out[field] = len(v)
        else:
            out[field] = "[object]"
        return out, f"Changed type of '{field}' from {type(v).__name__} to {type(out[field]).__name__}"
    if kind == "wrong_value":
        if isinstance(v, bool):
            out[field] = not v
        elif isinstance(v, (int, float)):
            out[field] = -abs(v) if v else -1
        elif isinstance(v, str):
            out[field] = "UNKNOWN"
        else:
            out[field] = None
        return out, f"Replaced '{field}' value {json.dumps(v)} with {json.dumps(out[field])} (still valid JSON)"
    return data, None


def raise_pre_fault(kind: str, node_label: str, timeout_ms: int | None) -> None:
    """Faults that replace execution entirely."""
    if kind == "http_500":
        raise NodeError("http_error", f"HTTP 500 Internal Server Error from {node_label} (simulated)",
                        details={"status_code": 500, "body": {"error": "internal_server_error"}}, simulated=True)
    if kind == "timeout":
        t = timeout_ms or 5000
        raise NodeError("timeout", f"{node_label} exceeded its {t} ms timeout (simulated)",
                        details={"timeout_ms": t}, simulated=True, duration_ms=float(t))


def apply_generic(kind: str, payload: Any, field: str | None) -> tuple[Any, str]:
    """Failure Simulator node behaviour on an arbitrary payload."""
    if kind in DATA_FAULTS:
        new, desc = apply_data(kind, payload, field)
        return new, desc or f"No-op: field '{field}' not present"
    if kind == "malformed_json":
        return truncate_json(payload), "Payload replaced by truncated JSON text"
    if kind == "empty_response":
        return {}, "Payload replaced by an empty object"
    if kind == "fail_validation":
        raise NodeError("validation_failed", "Injected validation failure", details={
            "errors": [{"field": "*", "code": "injected", "message": "Validation failure injected by Failure Simulator"}]},
            simulated=True)
    raise_pre_fault(kind, "Failure Simulator", None)
    return payload, "unknown fault"
