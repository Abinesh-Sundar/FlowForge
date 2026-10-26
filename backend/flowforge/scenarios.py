"""WhatIf AI — deterministic failure scenarios and their expected outcomes.

A scenario names a target node, a fault kind, and the outcome we *expect*. Pass/fail is decided by comparing
the real execution trace against that expectation — never by asking a model whether it looked right.
"""
from __future__ import annotations

from typing import Any


def _first(wf: dict, type_: str) -> dict | None:
    return next((n for n in wf.get("nodes", []) if n.get("type") == type_), None)


def build_catalog(wf: dict) -> list[dict]:
    llm, val, http = _first(wf, "llm"), _first(wf, "validator"), _first(wf, "http")
    out: list[dict] = []

    def add(**kw):
        out.append(kw)

    if llm:
        add(id="llm-malformed", name="Malformed LLM JSON", kind="malformed_json", target_node_id=llm["id"],
            description="The model returns prose-truncated JSON. The LLM node should reject it as unparseable.",
            expected={"status": "failed", "failing_node_id": llm["id"], "error_type": "malformed_json",
                      "text": f"'{llm.get('label')}' fails with a malformed_json parse error; downstream nodes never run."})
        add(id="llm-empty", name="Empty LLM response", kind="empty_response", target_node_id=llm["id"],
            description="The model returns an empty string.",
            expected={"status": "failed", "failing_node_id": llm["id"], "error_type": "empty_response",
                      "text": f"'{llm.get('label')}' fails with empty_response; no downstream node executes."})
        add(id="llm-timeout", name="LLM timeout", kind="timeout", target_node_id=llm["id"],
            description="The model call exceeds its configured timeout budget.",
            expected={"status": "failed", "failing_node_id": llm["id"], "error_type": "timeout",
                      "text": f"'{llm.get('label')}' fails with a timeout error."})
    if val:
        fields = [r.get("field") for r in (val.get("config") or {}).get("rules", [])] or ["amount"]
        f0 = fields[0]
        add(id="val-wrong-type", name=f"LLM returns '{f0}' as a string", kind="wrong_type", field=f0,
            target_node_id=llm["id"] if llm else val["id"],
            description=f"The model emits {f0} as a string instead of its contracted type. Validation should catch it.",
            expected={"status": "degraded", "failing_node_id": val["id"], "error_type": "validation_failed",
                      "text": f"'{val.get('label')}' rejects the payload with a type error on '{f0}', and the "
                              f"error-handler branch absorbs it (run degraded, not crashed)."})
        add(id="val-missing", name=f"Missing required field '{f0}'", kind="missing_field", field=f0,
            target_node_id=llm["id"] if llm else val["id"],
            description=f"The model omits {f0} entirely.",
            expected={"status": "degraded", "failing_node_id": val["id"], "error_type": "validation_failed",
                      "text": f"'{val.get('label')}' rejects the payload: required field '{f0}' is missing. "
                              f"The error handler absorbs it."})
        add(id="val-wrong-value", name=f"Valid JSON, wrong value for '{f0}'", kind="wrong_value", field=f0,
            target_node_id=llm["id"] if llm else val["id"],
            description=f"The payload is well-typed but {f0} carries an implausible value (e.g. negative / UNKNOWN).",
            expected={"status": "degraded", "failing_node_id": val["id"], "error_type": "validation_failed",
                      "text": "Presence passes, but the value rule rejects the record; error handler absorbs it."})
        add(id="val-forced", name="Forced validation failure", kind="fail_validation", target_node_id=val["id"],
            description="Validation is forced to fail regardless of payload, isolating the error path.",
            expected={"status": "degraded", "failing_node_id": val["id"], "error_type": "validation_failed",
                      "text": f"'{val.get('label')}' fails deterministically and routes to the error handler."})
    if http:
        add(id="http-500", name="HTTP 500 from downstream ERP", kind="http_500", target_node_id=http["id"],
            description="The ERP mock returns 500. The workflow should route to its error handler, not crash.",
            expected={"status": "degraded", "failing_node_id": http["id"], "error_type": "http_error",
                      "text": "The HTTP node fails; the error-handler Output node still runs, so the run is degraded."})
        add(id="http-timeout", name="Downstream ERP timeout", kind="timeout", target_node_id=http["id"],
            description="The ERP call exceeds its timeout.",
            expected={"status": "degraded", "failing_node_id": http["id"], "error_type": "timeout",
                      "text": "The HTTP node times out; the error-handler branch completes and the run is degraded."})
        add(id="http-empty", name="Empty response from downstream API", kind="empty_response",
            target_node_id=http["id"],
            description="The API answers 200 with an empty body.",
            expected={"status": "degraded", "failing_node_id": http["id"], "error_type": "empty_response",
                      "text": "The empty body is rejected; the error handler completes and the run is degraded."})
    return out


def evaluate(trace: dict, expected: dict) -> dict:
    failed = [s for s in trace["steps"] if s["status"] == "failed"]
    checks = []
    checks.append({"check": "Execution status", "expected": expected.get("status"),
                   "actual": trace["status"], "pass": trace["status"] == expected.get("status")})
    if expected.get("failing_node_id"):
        actual_node = failed[0]["node_id"] if failed else None
        checks.append({"check": "Failing node", "expected": expected["failing_node_id"], "actual": actual_node,
                       "pass": actual_node == expected["failing_node_id"]})
    if expected.get("error_type"):
        actual_err = failed[0]["error"]["type"] if failed and failed[0].get("error") else None
        checks.append({"check": "Error type", "expected": expected["error_type"], "actual": actual_err,
                       "pass": actual_err == expected["error_type"]})
    # If the scenario's fault never reached its target (an upstream node failed first), the result is
    # inconclusive rather than a false failure — say so explicitly.
    target = expected.get("failing_node_id")
    applied = any((s.get("meta") or {}).get("scenario_fault", {}).get("applied") for s in trace["steps"])
    blocked = bool(failed) and target and failed[0]["node_id"] != target and not applied
    passed = all(c["pass"] for c in checks)
    if blocked:
        passed = False
    return {"passed": passed, "blocked": blocked, "checks": checks,
            "blocked_reason": ("An upstream node failed before this scenario's fault could be applied. "
                               "Fix the earlier failure first, or target that node instead.") if blocked else None,
            "actual_behavior": {
                "status": trace["status"],
                "failing_node": (failed[0]["label"] if failed else None),
                "error": (failed[0]["error"]["message"] if failed and failed[0].get("error") else None),
                "outputs": trace.get("outputs", []),
            }}


def activity_checks(trace: dict) -> list[dict]:
    """Extra sanity checks appended to a scenario result (guardrail behaviour, not pass/fail core)."""
    out = []
    failed = [s for s in trace["steps"] if s["status"] == "failed"]
    if failed:
        out.append({"check": "Failure is clearly marked simulated/real",
                    "pass": True,
                    "detail": "simulated" if failed[0].get("simulated") else
                              ("real fault" if not trace.get("scenario") else "fault injected by WhatIf (real code path)")})
    skipped = [s["label"] for s in trace["steps"] if s["status"] == "skipped"]
    if skipped:
        out.append({"check": "Unaffected branches skipped", "pass": True, "detail": ", ".join(skipped)})
    return out


def find_scenario(wf: dict, scenario_id: str) -> dict | None:
    return next((s for s in build_catalog(wf) if s["id"] == scenario_id), None)


def custom_scenario(kind: str, target_node_id: str, field: str | None, expected_status: str,
                    expected_error: str | None) -> dict[str, Any]:
    return {"id": f"custom-{kind}", "name": f"Custom: {kind} on {target_node_id}", "kind": kind,
            "target_node_id": target_node_id, "field": field, "description": "Ad-hoc scenario",
            "expected": {"status": expected_status, "error_type": expected_error, "text": "User-defined expectation"}}
