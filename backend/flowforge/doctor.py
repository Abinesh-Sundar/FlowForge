"""AI Workflow Doctor — evidence-backed diagnosis, proposed fixes, and verified regression comparison.

Diagnosis is a *hypothesis*. A fix is only accepted once deterministic regression tests pass.
"""
from __future__ import annotations

import copy
import json
import os
import time
from typing import Any

from . import llm
from .graph import execute
from .redact import redact
from .scenarios import build_catalog

ROOT_CAUSE_DB = {
    "validation_failed": {
        "missing": "The upstream LLM response omits a field the validator requires. The extraction prompt does not "
                   "enumerate every required field, so the model silently drops it.",
        "type": "The upstream LLM emits a field with the wrong JSON type. The prompt asks for JSON but never pins "
                "the field's type, so the model copies the formatted value (currency symbols, separators) verbatim.",
        "pattern": "A field's value does not match the required format. The prompt does not specify the expected "
                   "format, so the model's output is rejected downstream.",
        "min": "A numeric field is outside its accepted range; validation is doing its job, but the upstream "
               "contract does not state the range so the model cannot know.",
        "max": "A numeric field is outside its accepted range.",
        "forbidden": "The model produced a sentinel value the validator rejects.",
        "injected": "Validation was forced to fail by a scenario; there is no production defect to repair.",
    },
    "malformed_json": "The LLM node parses the model's text as JSON, but the prompt does not require a JSON-only "
                      "response, so surrounding prose makes the payload unparseable.",
    "empty_response": "The model (or the downstream endpoint) returned an empty body; the node correctly refuses "
                      "to pass empty data downstream.",
    "timeout": "The call exceeded its configured timeout. Either the timeout budget is too tight or the dependency "
               "is unhealthy; this is an infrastructure condition, not a prompt defect.",
    "http_error": "The downstream endpoint returned an error status. The error-handler branch is the right place to "
                  "absorb this; the workflow itself is behaving correctly.",
    "condition_error": "The condition references a field the payload does not contain.",
}


def _upstream(wf: dict, node_id: str, type_: str) -> dict | None:
    """Find the nearest upstream node of a given type."""
    by_id = {n["id"]: n for n in wf.get("nodes", [])}
    rev = {}
    for e in wf.get("edges", []):
        rev.setdefault(e["target"], []).append(e["source"])
    seen, q = set(), list(rev.get(node_id, []))
    while q:
        cur = q.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        if by_id.get(cur, {}).get("type") == type_:
            return by_id[cur]
        q.extend(rev.get(cur, []))
    return None


# ---------------------------------------------------------------- deterministic diagnosis
def diagnose_deterministic(trace: dict, wf: dict) -> dict:
    failed = next((s for s in trace["steps"] if s["status"] == "failed"), None)
    if not failed:
        return {"source": "deterministic", "failed_node_id": None, "confidence": "n/a",
                "summary": "No failing node found in this execution trace.",
                "root_cause": "The execution completed without a node failure.",
                "evidence": [], "proposals": []}

    err = failed.get("error") or {}
    etype = err.get("type", "unknown")
    details = err.get("details") or {}
    evidence: list[dict] = []
    evidence.append({"source": "execution", "node_id": failed["node_id"], "node": failed["label"],
                     "fact": f"Node '{failed['label']}' failed with {etype} after {failed['duration_ms']} ms",
                     "detail": err.get("message")})
    subtype = None
    if etype == "validation_failed":
        errors = details.get("errors") or []
        if errors:
            subtype = errors[0].get("code")
            for e in errors:
                evidence.append({"source": "validator", "node_id": failed["node_id"], "node": failed["label"],
                                 "fact": f"Field '{e.get('field')}' -> {e.get('code')}",
                                 "detail": e.get("message"), "expected": e.get("expected"), "actual": e.get("actual")})

    # capture upstream raw output as the concrete trigger
    order = [s["node_id"] for s in trace["steps"]]
    idx = order.index(failed["node_id"]) if failed["node_id"] in order else 0
    upstream = [s for s in trace["steps"][:idx] if s["status"] == "succeeded"]
    if upstream:
        u = upstream[-1]
        raw = (u.get("meta") or {}).get("raw_output")
        if raw:
            evidence.append({"source": "llm", "node_id": u["node_id"], "node": u["label"],
                             "fact": "Upstream model output", "detail": raw[:600]})
        evidence.append({"source": "execution", "node_id": u["node_id"], "node": u["label"],
                         "fact": f"Upstream node completed with output {json.dumps(u.get('output'))[:300]}"})

    llm_node = _upstream(wf, failed["node_id"], "llm") if etype == "validation_failed" else None
    validator_node = (next((n for n in wf.get("nodes", []) if n["id"] == failed["node_id"]), None)
                      if failed.get("type") == "validator" else None)
    proposals: list[dict] = []

    if validator_node and llm_node and subtype in ("type", "pattern", "missing", "min", "max", "forbidden"):
        bad_fields = sorted({e["field"] for e in details.get("errors", []) if e.get("code") == subtype})
        proposals.append(_prompt_fix(llm_node, bad_fields, details.get("errors", []), recommended=True))
        if subtype == "type":
            proposals.append(_validator_relax_fix(validator_node, bad_fields, recommended=False))
    elif etype in ("malformed_json", "empty_response") and failed.get("type") == "llm":
        node = next((n for n in wf.get("nodes", []) if n["id"] == failed["node_id"]), None)
        if node:
            proposals.append(_json_only_fix(node))
    elif etype in ("timeout", "http_error", "empty_response") and failed.get("type") == "http":
        evidence.append({"source": "workflow", "node_id": failed["node_id"], "node": failed["label"],
                         "fact": "Error-handler edge is configured",
                         "detail": "This failure is environmental; the run degrades rather than crashing. "
                                   "A retry/timeout configuration change is the appropriate mitigation."})
        proposals.append(_timeout_fix(failed))
    elif subtype == "injected":
        evidence.append({"source": "simulation", "node_id": failed["node_id"], "node": failed["label"],
                         "fact": "Fault was injected by the scenario",
                         "detail": "Remove the scenario to test the real workflow."})

    root = ROOT_CAUSE_DB.get(etype, "The node raised an unclassified error; inspect its input and configuration.")
    if isinstance(root, dict):
        root = root.get(subtype or "", root.get("type"))

    return {
        "source": "deterministic",
        "label": "Deterministic diagnosis (no API key required)",
        "failed_node_id": failed["node_id"],
        "failed_node_label": failed["label"],
        "confidence": "high" if evidence else "medium",
        "summary": f"'{failed['label']}' is the first failing node. " + root,
        "root_cause": root,
        "evidence": evidence,
        "proposals": proposals,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _prompt_fix(llm_node: dict, fields: list[str], errors: list[dict], recommended: bool) -> dict:
    cfg = llm_node.get("config") or {}
    prompt = cfg.get("prompt", "")
    rules = []
    for f in fields:
        rules.append({"field": f, "expected": next((e.get("expected") for e in errors if e.get("field") == f), None)})
    addition = ("\n\nStrict output contract:\n"
                "- Return ONLY a single JSON object. No prose, no markdown fences, no commentary.\n"
                "- `amount` MUST be a JSON number (not a string): strip currency symbols and thousands separators.\n"
                "- `date` MUST be an ISO 8601 date (YYYY-MM-DD).\n"
                "- Include every key, using null only when the document genuinely omits it.")
    new_prompt = prompt.rstrip() + addition
    return {
        "id": "prop-prompt-contract",
        "title": "Tighten the extraction prompt with an explicit output contract",
        "summary": "Pin the types and format of the fields that validation rejected, and require JSON-only output. "
                   "This fixes the defect at its source (the model's contract) instead of weakening downstream checks.",
        "target_node_id": llm_node["id"],
        "target_node_label": llm_node.get("label"),
        "confidence": "high",
        "risk": "low",
        "recommended": recommended,
        "diff": [{"config_key": "prompt", "before": prompt, "after": new_prompt}],
        "expected_effect": f"Model returns numeric {', '.join(fields) or 'values'} and JSON-only text; "
                           f"'{llm_node.get('label')}' passes validation.",
        "apply": [{"op": "set_config", "node_id": llm_node["id"], "path": "prompt", "value": new_prompt}],
        "rule_context": rules,
    }


def _validator_relax_fix(validator_node: dict, fields: list[str], recommended: bool) -> dict:
    rules = copy.deepcopy((validator_node.get("config") or {}).get("rules", []))
    after = copy.deepcopy(rules)
    ops = []
    for i, r in enumerate(after):
        if r.get("field") in fields and r.get("type") in ("number", "integer"):
            ops.append({"op": "set_config", "node_id": validator_node["id"], "path": f"rules.{i}.type", "value": "string"})
    return {
        "id": "prop-relax-validator",
        "title": "Relax the validator to accept strings",
        "summary": f"Change the type contract for {', '.join(fields)} from number to string. This silences the "
                   "symptom but would push unformatted values into the downstream ERP call.",
        "target_node_id": validator_node["id"],
        "target_node_label": validator_node.get("label"),
        "confidence": "low",
        "risk": "high",
        "recommended": recommended,
        "diff": [{"config_key": "rules", "before": rules, "after": after}],
        "expected_effect": "Validation passes, but downstream CONTAINS/amount> threshold logic receives a string.",
        "apply": ops,
    }


def _json_only_fix(llm_node: dict) -> dict:
    prompt = (llm_node.get("config") or {}).get("prompt", "")
    new = prompt.rstrip() + "\n\nReturn ONLY the JSON object. No prose, no markdown fences."
    return {
        "id": "prop-json-only", "title": "Require a JSON-only response",
        "summary": "Remove the prose that breaks parsing by making the JSON-only requirement explicit.",
        "target_node_id": llm_node["id"], "target_node_label": llm_node.get("label"),
        "confidence": "high", "risk": "low", "recommended": True,
        "diff": [{"config_key": "prompt", "before": prompt, "after": new}],
        "expected_effect": "Model output parses as JSON on the first attempt.",
        "apply": [{"op": "set_config", "node_id": llm_node["id"], "path": "prompt", "value": new}],
    }


def _timeout_fix(node: dict) -> dict:
    cfg = node.get("config") or {}
    before = cfg.get("timeout_ms", 5000)
    after = max(int(before), 15000)
    return {
        "id": "prop-timeout", "title": "Raise the HTTP timeout budget",
        "summary": "The dependency is slow rather than incorrect; a larger timeout avoids spurious failures.",
        "target_node_id": node["id"], "target_node_label": node.get("label"),
        "confidence": "medium", "risk": "medium", "recommended": True,
        "diff": [{"config_key": "timeout_ms", "before": before, "after": after}],
        "expected_effect": "Fewer timeouts under normal load; note the underlying latency remains.",
        "apply": [{"op": "set_config", "node_id": node["id"], "path": "timeout_ms", "value": after}],
    }


# ---------------------------------------------------------------- live Claude diagnosis
DOCTOR_SYSTEM = """You are the AI Workflow Doctor for FlowForge. You diagnose failing AI workflow executions.
You receive a redacted execution trace and the workflow definition. Identify the most likely failing node and
probable cause, citing concrete evidence from the trace. Propose ONE targeted configuration change.
Respond with a single JSON object only, using this schema:
{"summary": string, "root_cause": string, "failed_node_id": string,
 "evidence": [{"source": string, "node_id": string, "fact": string, "detail": string}],
 "proposal": {"title": string, "summary": string, "target_node_id": string,
              "config_key": "prompt"|"rules"|"timeout_ms", "new_value": any, "expected_effect": string}}
Do not propose code execution. Do not claim certainty: this is a hypothesis to be verified by regression tests."""


def diagnose_live(trace: dict, wf: dict, timeout_s: float = 45.0) -> dict:
    context = {
        "workflow": {"id": wf.get("id"), "name": wf.get("name"), "nodes":
            [{"id": n["id"], "type": n["type"], "label": n.get("label"), "config": n.get("config")}
             for n in wf.get("nodes", [])]},
        "trace": {"status": trace["status"], "scenario": trace.get("scenario"),
                  "steps": [{"node_id": s["node_id"], "label": s["label"], "status": s["status"],
                             "duration_ms": s["duration_ms"], "error": s["error"], "output": s.get("output"),
                             "meta": {k: v for k, v in (s.get("meta") or {}).items()
                                      if k in ("raw_output", "errors", "checked_fields")}}
                            for s in trace["steps"]]},
    }
    model = os.environ.get("FLOWFORGE_MODEL", llm.DEFAULT_MODEL)
    r = llm.call_model(model, json.dumps(redact(context), indent=2), None, system=DOCTOR_SYSTEM, timeout_s=timeout_s)
    data = llm.parse_json_text(r["text"])
    proposals = []
    p = data.get("proposal") or {}
    if p.get("target_node_id"):
        node = next((n for n in wf["nodes"] if n["id"] == p["target_node_id"]), None)
        if node:
            before = (node.get("config") or {}).get(p.get("config_key"))
            proposals.append({
                "id": "prop-claude", "title": p.get("title", "Claude-proposed change"),
                "summary": p.get("summary", ""), "target_node_id": node["id"],
                "target_node_label": node.get("label"), "confidence": "medium", "risk": "medium", "recommended": True,
                "diff": [{"config_key": p.get("config_key"), "before": before, "after": p.get("new_value")}],
                "expected_effect": p.get("expected_effect", ""),
                "apply": [{"op": "set_config", "node_id": node["id"], "path": p.get("config_key"),
                           "value": p.get("new_value")}],
            })
    u = r["usage"]
    return {
        "source": "claude",
        "label": f"AI diagnosis via {llm.provider_label()} ({r['model']})",
        "model": r["model"],
        "provider": llm.provider_label(),
        "usage": u,
        "cost_usd": llm.estimate_cost(model, u["input_tokens"], u["output_tokens"]),
        "cost_estimated": True,
        "failed_node_id": data.get("failed_node_id"),
        "confidence": "medium",
        "summary": data.get("summary", ""),
        "root_cause": data.get("root_cause", ""),
        "evidence": data.get("evidence", []),
        "proposals": proposals,
        "disclaimer": f"{llm.provider_label()}'s diagnosis is a hypothesis. It is verified by deterministic regression tests, "
                      "and no change is applied without your approval.",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def diagnose(trace: dict, wf: dict, live: bool = False) -> dict:
    if live and llm.live_available():
        try:
            return diagnose_live(trace, wf)
        except Exception as e:  # fall back, never fail the UI
            d = diagnose_deterministic(trace, wf)
            d["fallback_reason"] = (f"Live diagnosis via {llm.provider_label()} failed "
                                    f"({type(e).__name__}: {e}); showing deterministic diagnosis.")
            return d
    d = diagnose_deterministic(trace, wf)
    if live and not llm.live_available():
        d["fallback_reason"] = ("Live diagnosis requested but no API key is configured on the server "
                                "(set ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in backend/.env).")
    return d


# ---------------------------------------------------------------- apply
def set_path(node: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Any = node["config"] if path.split(".")[0] not in ("id", "type", "label", "position") else node
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def apply_proposal(workflow: dict, proposal: dict) -> dict:
    """Return a modified deep copy of the workflow. Never mutates the input."""
    wf = copy.deepcopy(workflow)
    by_id = {n["id"]: n for n in wf.get("nodes", [])}
    for op in proposal.get("apply", []):
        node = by_id.get(op["node_id"])
        if node is None:
            raise ValueError(f"Target node {op['node_id']} no longer exists")
        if op["op"] != "set_config":
            raise ValueError(f"Unsupported operation {op['op']}")
        set_path(node, op["path"], op["value"])
    return wf


# ---------------------------------------------------------------- regression
DEFAULT_SUITE = [
    {"id": "reg-happy", "name": "Invoice happy path completes", "kind": "run", "scenario": None,
     "expected_status": "succeeded"},
    {"id": "reg-malformed", "name": "Malformed model JSON is rejected", "kind": "scenario",
     "scenario_id": "llm-malformed", "expected_status": "failed"},
    {"id": "reg-erp500", "name": "ERP 500 degrades through the error handler", "kind": "scenario",
     "scenario_id": "http-500", "expected_status": "degraded"},
    {"id": "reg-review", "name": "Sub-threshold invoice routes to manual review", "kind": "payload",
     "scenario": None, "expected_status": "succeeded", "outcome": "review"},
    {"id": "reg-type", "name": "Type contract rejects string amounts", "kind": "scenario",
     "scenario_id": "val-wrong-type", "expected_status": "degraded"},
    {"id": "reg-missing", "name": "Missing required field is rejected", "kind": "scenario",
     "scenario_id": "val-missing", "expected_status": "degraded"},
]


def run_regression(wf: dict, payload: Any, *, llm_mode: str = "mock", catalog: list[dict] | None = None) -> dict:
    catalog = catalog if catalog is not None else build_catalog(wf)
    results = []
    for t in DEFAULT_SUITE:
        scenario = None
        if t["kind"] == "scenario":
            base = next((s for s in catalog if s["id"] == t["scenario_id"]), None)
            if base is None:
                results.append({**t, "passed": False, "actual_status": None,
                                "reason": "Scenario not available for this workflow"})
                continue
            scenario = {k: base.get(k) for k in ("id", "name", "kind", "target_node_id", "field", "expected")}
        run_payload = payload
        if t["kind"] == "payload":
            run_payload = json.loads(json.dumps(payload)) if isinstance(payload, dict) else payload
            if isinstance(run_payload, dict) and isinstance(run_payload.get("document"), str):
                run_payload["document"] = run_payload["document"].replace("1,250.00", "42.50")
        trace = execute(wf, run_payload, llm_mode=llm_mode, scenario=scenario)
        passed = trace["status"] == t["expected_status"]
        if t.get("outcome"):
            passed = passed and any(o.get("outcome") == t["outcome"] for o in trace["outputs"])
        results.append({**t, "passed": passed, "actual_status": trace["status"], "execution_id": trace["execution_id"],
                        "outcomes": [o.get("outcome") for o in trace["outputs"]], "trace": trace})
    return {"suite": "default", "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "passed": sum(1 for r in results if r["passed"]), "total": len(results),
            "results": results}


def compare(before: dict, after: dict) -> dict:
    rows = []
    for b, a in zip(before["results"], after["results"]):
        rows.append({"name": b["name"], "before": "PASS" if b["passed"] else "FAIL",
                     "after": "PASS" if a["passed"] else "FAIL", "changed": b["passed"] != a["passed"],
                     "before_status": b["actual_status"], "after_status": a["actual_status"]})
    bpassed, apassed = before["passed"], after["passed"]
    return {"rows": rows, "before_passed": bpassed, "after_passed": apassed, "total": before["total"],
            "improved": apassed > bpassed, "regressed": apassed < bpassed,
            "summary": f"{apassed}/{after['total']} regression checks pass after the change "
                       f"(was {bpassed}/{before['total']})."}
