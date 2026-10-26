"""Node executors. Each is deterministic given (config, input) — no user-supplied code is ever evaluated."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from . import faults, llm
from .errors import NodeError

FAST = os.environ.get("FLOWFORGE_FAST") == "1"  # skip simulated latency (tests)
HTTP_ALLOWLIST = [h.strip().lower() for h in os.environ.get("FLOWFORGE_HTTP_ALLOWLIST", "").split(",") if h.strip()]

NODE_TYPES = ["input", "llm", "transform", "validator", "condition", "http", "failure_sim", "output"]
VALIDATOR_TYPES = {"string", "number", "integer", "boolean", "object", "array"}
CONDITION_OPS = {"==", "!=", ">", ">=", "<", "<=", "exists", "contains"}
TRANSFORM_OPS = {"pick", "omit", "set", "rename", "to_number", "uppercase", "lowercase"}


@dataclass
class Ctx:
    llm_mode: str = "mock"           # "mock" | "live"
    fault: dict | None = None        # {"kind", "field"} injected on this node by a WhatIf scenario
    fault_notes: list[str] = field(default_factory=list)
    fault_applied: bool = False


@dataclass
class Result:
    output: Any
    handle: str = "out"
    meta: dict = field(default_factory=dict)


def get_path(data: Any, path: str) -> tuple[bool, Any]:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def _sleep(ms: float) -> None:
    if not FAST:
        time.sleep(ms / 1000)


# ------------------------------------------------------------------ input / output
def run_input(cfg, inp, ctx: Ctx) -> Result:
    return Result(inp)


def run_output(cfg, inp, ctx: Ctx) -> Result:
    return Result(inp, meta={"outcome": cfg.get("outcome", "success")})


# ------------------------------------------------------------------ claude llm
def run_llm(cfg, inp, ctx: Ctx) -> Result:
    prompt = cfg.get("prompt", "")
    model = cfg.get("model") or llm.DEFAULT_MODEL
    live = ctx.llm_mode == "live"
    if live and not llm.live_available():
        raise NodeError("config_error", "Live mode requested but no API key is configured on the server "
                                        "(set ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in backend/.env)")
    if ctx.fault and ctx.fault["kind"] in ("timeout", "http_500"):
        ctx.fault_applied = True
        ctx.fault_notes.append(f"{ctx.fault['kind']} injected before the model call")
        faults.raise_pre_fault(ctx.fault["kind"], "Claude LLM call", cfg.get("timeout_ms", 30000))
    meta: dict[str, Any] = {"mocked": not live,
                            "model": llm.active_model(model) if live else "mock-extractor (deterministic)",
                            "provider": llm.provider_label() if live else "mock"}
    if live:
        r = llm.call_model(model, prompt, inp, cfg.get("system"), cfg.get("timeout_ms", 30000) / 1000)
        raw = r["text"]
        u = r["usage"]
        meta.update(model=r["model"], provider=llm.provider_label(), usage=u,
                    cost_usd=llm.estimate_cost(model, u["input_tokens"], u["output_tokens"]),
                    cost_estimated=True, request_id=r["request_id"], stop_reason=r["stop_reason"])
    else:
        _sleep(350)
        raw = llm.mock_extract(prompt, inp)
        meta.update(usage=None, cost_usd=None, note="Mock model: token usage and cost are not available")
    if ctx.fault and ctx.fault["kind"] in faults.RAW_FAULTS:
        raw, note = faults.apply_raw(ctx.fault["kind"], raw)
        ctx.fault_applied = True
        ctx.fault_notes.append(note)
    meta["raw_output"] = raw
    if cfg.get("output", "json") == "json":
        data = llm.parse_json_text(raw)
        if ctx.fault and ctx.fault["kind"] in faults.DATA_FAULTS:
            data, note = faults.apply_data(ctx.fault["kind"], data, ctx.fault.get("field"))
            if note:
                ctx.fault_applied = True
                ctx.fault_notes.append(note)
                meta["scenario_fault_note"] = note
        return Result(data, meta=meta)
    return Result(raw, meta=meta)


# ------------------------------------------------------------------ validator
def _type_ok(v: Any, t: str) -> bool:
    if t == "string":
        return isinstance(v, str)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "object":
        return isinstance(v, dict)
    return isinstance(v, list)


def validate_rules(rules: list[dict], data: Any) -> list[dict]:
    if not isinstance(data, dict):
        return [{"field": "*", "code": "type", "message": f"Expected a JSON object but received {type(data).__name__}",
                 "expected": "object", "actual": type(data).__name__}]
    errors = []
    for r in rules:
        f, t = r["field"], r.get("type", "string")
        present = f in data and data[f] is not None
        if not present:
            if r.get("required", True):
                errors.append({"field": f, "code": "missing", "message": f"Required field '{f}' is missing",
                               "expected": t, "actual": None})
            continue
        v = data[f]
        if not _type_ok(v, t):
            errors.append({"field": f, "code": "type", "expected": t, "actual": json.dumps(v),
                           "message": f"'{f}' expected {t} but got {type(v).__name__} ({json.dumps(v)})"})
            continue
        if r.get("pattern") and isinstance(v, str) and not re.search(r["pattern"], v):
            errors.append({"field": f, "code": "pattern", "expected": r["pattern"], "actual": v,
                           "message": f"'{f}' value {json.dumps(v)} does not match pattern {r['pattern']}"})
        if r.get("min") is not None and isinstance(v, (int, float)) and v < r["min"]:
            errors.append({"field": f, "code": "min", "expected": f">= {r['min']}", "actual": v,
                           "message": f"'{f}' value {v} is below the minimum {r['min']}"})
        if r.get("max") is not None and isinstance(v, (int, float)) and v > r["max"]:
            errors.append({"field": f, "code": "max", "expected": f"<= {r['max']}", "actual": v,
                           "message": f"'{f}' value {v} is above the maximum {r['max']}"})
        if r.get("not_in") and v in r["not_in"]:
            errors.append({"field": f, "code": "forbidden", "expected": f"not in {r['not_in']}", "actual": v,
                           "message": f"'{f}' value {json.dumps(v)} is not an acceptable value"})
    return errors


def run_validator(cfg, inp, ctx: Ctx) -> Result:
    if ctx.fault and ctx.fault["kind"] == "fail_validation":
        ctx.fault_applied = True
        ctx.fault_notes.append("Validation forced to fail")
        raise NodeError("validation_failed", "Validation failed (injected by WhatIf scenario)", simulated=True,
                        details={"errors": [{"field": "*", "code": "injected",
                                             "message": "Validation failure injected by scenario"}]})
    rules = cfg.get("rules", [])
    errors = validate_rules(rules, inp)
    meta = {"checked_fields": [r["field"] for r in rules], "errors": errors, "valid": not errors}
    if errors:
        raise NodeError("validation_failed",
                        f"{len(errors)} validation error(s): " + "; ".join(e["message"] for e in errors),
                        details={"errors": errors, "checked_fields": meta["checked_fields"]})
    return Result(inp, meta=meta)


# ------------------------------------------------------------------ condition
def run_condition(cfg, inp, ctx: Ctx) -> Result:
    path, op, expected = cfg["field"], cfg["operator"], cfg.get("value")
    found, actual = get_path(inp, path)
    if op == "exists":
        res = found and actual is not None
    else:
        if not found:
            raise NodeError("condition_error", f"Condition field '{path}' not found in input")
        try:
            if op in (">", ">=", "<", "<="):
                a, b = float(actual), float(expected)
                res = {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]
            elif op == "==":
                res = actual == expected or str(actual) == str(expected)
            elif op == "!=":
                res = not (actual == expected or str(actual) == str(expected))
            else:
                res = str(expected) in (actual if isinstance(actual, (str, list)) else str(actual))
        except (TypeError, ValueError):
            raise NodeError("condition_error", f"Cannot compare {json.dumps(actual)} {op} {json.dumps(expected)}")
    return Result(inp, handle="true" if res else "false",
                  meta={"expression": f"{path} {op} {json.dumps(expected)}", "actual": actual, "result": bool(res)})


# ------------------------------------------------------------------ transform
def run_transform(cfg, inp, ctx: Ctx) -> Result:
    data = dict(inp) if isinstance(inp, dict) else {"value": inp}
    applied = []
    for op in cfg.get("ops", []):
        k = op["op"]
        if k == "pick":
            data = {f: data[f] for f in op["fields"] if f in data}
        elif k == "omit":
            data = {f: v for f, v in data.items() if f not in op["fields"]}
        elif k == "set":
            if "from" in op:
                found, v = get_path(data, op["from"])
                if not found:
                    raise NodeError("transform_error", f"set: source path '{op['from']}' not found")
                data[op["field"]] = v
            else:
                data[op["field"]] = op.get("value")
        elif k == "rename":
            if op["from"] not in data:
                raise NodeError("transform_error", f"rename: field '{op['from']}' not found")
            data[op["to"]] = data.pop(op["from"])
        elif k == "to_number":
            f = op["field"]
            if f not in data:
                raise NodeError("transform_error", f"to_number: field '{f}' not found")
            try:
                data[f] = float(re.sub(r"[^\d.\-]", "", str(data[f]).replace(",", "")))
            except ValueError:
                raise NodeError("transform_error", f"to_number: cannot parse {json.dumps(data[f])}")
        elif k in ("uppercase", "lowercase"):
            f = op["field"]
            if isinstance(data.get(f), str):
                data[f] = data[f].upper() if k == "uppercase" else data[f].lower()
        applied.append(k)
    return Result(data, meta={"ops_applied": applied})


# ------------------------------------------------------------------ http
def _check_url(url: str):
    u = urlparse(url)
    if u.scheme == "mock":
        return u
    if u.scheme != "https" or not u.hostname:
        raise NodeError("config_error",
                        f"URL scheme '{u.scheme}' is not allowed (use mock:// or an allow-listed https host)")
    if u.hostname.lower() not in HTTP_ALLOWLIST:
        raise NodeError("config_error", f"Host '{u.hostname}' is not in FLOWFORGE_HTTP_ALLOWLIST")
    for info in socket.getaddrinfo(u.hostname, u.port or 443):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise NodeError("config_error", f"Host '{u.hostname}' resolves to a non-public address")
    return u


def mock_http(method: str, u, body: Any) -> tuple[int, Any]:
    path = u.netloc + u.path
    if path.startswith("status/"):
        code = int(path.split("/")[1])
        return code, ({"ok": True} if code < 400 else {"error": f"mock status {code}"})
    if path == "erp/invoices":
        if method != "POST":
            return 405, {"error": "method not allowed"}
        if not isinstance(body, dict) or not body.get("invoice_number") or \
                not isinstance(body.get("amount"), (int, float)):
            return 422, {"error": "invoice_number and numeric amount are required"}
        ref = "ERP-" + hashlib.sha1(str(body["invoice_number"]).encode()).hexdigest()[:8].upper()
        return 201, {"erp_ref": ref, "status": "posted", "amount": body["amount"]}
    if path == "empty":
        return 200, None
    return 404, {"error": f"unknown mock endpoint {path}"}


def run_http(cfg, inp, ctx: Ctx) -> Result:
    method, url = cfg.get("method", "POST").upper(), cfg["url"]
    if ctx.fault and ctx.fault["kind"] in ("http_500", "timeout"):
        ctx.fault_applied = True
        ctx.fault_notes.append(f"{ctx.fault['kind']} injected before the request was sent")
        faults.raise_pre_fault(ctx.fault["kind"], "HTTP Request", cfg.get("timeout_ms", 5000))
    u = _check_url(url)
    if u.scheme == "mock":
        _sleep(120)
        status, body = mock_http(method, u, inp)
    else:
        import httpx
        try:
            r = httpx.request(method, url, json=inp if method != "GET" else None,
                              timeout=cfg.get("timeout_ms", 5000) / 1000, follow_redirects=False)
        except httpx.TimeoutException:
            raise NodeError("timeout", f"Request to {u.hostname} timed out")
        except httpx.HTTPError as e:
            raise NodeError("http_error", f"Request failed: {type(e).__name__}")
        status = r.status_code
        try:
            body = r.json() if r.content else None
        except ValueError:
            body = r.text[:2000] or None
    if ctx.fault and ctx.fault["kind"] == "empty_response":
        ctx.fault_applied = True
        ctx.fault_notes.append("Response body replaced with empty body")
        body = None
    if status >= 400:
        raise NodeError("http_error", f"HTTP {status} from {url}", details={"status_code": status, "body": body})
    if body in (None, "", {}):
        raise NodeError("empty_response", f"HTTP {status} from {url} returned an empty body",
                        details={"status_code": status})
    out = dict(inp) if isinstance(inp, dict) else {"input": inp}
    out["http_response"] = {"status_code": status, "body": body}
    return Result(out, meta={"mocked": u.scheme == "mock", "url": url, "method": method, "status_code": status})


# ------------------------------------------------------------------ failure simulator
def run_failure_sim(cfg, inp, ctx: Ctx) -> Result:
    if not cfg.get("enabled", True):
        return Result(inp, meta={"enabled": False})
    kind = cfg.get("failure", "http_500")
    out, note = faults.apply_generic(kind, inp, cfg.get("field"))
    return Result(out, meta={"injected": kind, "note": note, "simulated": True})


EXECUTORS = {"input": run_input, "llm": run_llm, "transform": run_transform, "validator": run_validator,
             "condition": run_condition, "http": run_http, "failure_sim": run_failure_sim, "output": run_output}
