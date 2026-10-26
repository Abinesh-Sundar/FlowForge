"""Workflow graph validation and deterministic execution with tracing."""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from typing import Any

from . import nodes as N
from .errors import GraphInvalid, NodeError
from .redact import redact

OUTPUT_HANDLES = {"condition": {"true", "false"}, "default": {"out"}}
ERROR_HANDLE = "error"


# ------------------------------------------------------------------ validation
def _node_issues(node: dict) -> list[dict]:
    t, c, nid = node.get("type"), node.get("config") or {}, node.get("id")
    label = node.get("label") or nid

    def issue(msg: str, severity: str = "error") -> dict:
        return {"node_id": nid, "node_label": label, "message": msg, "severity": severity, "code": "config"}

    out = []
    if t not in N.NODE_TYPES:
        return [issue(f"Unknown node type '{t}'")]
    if t == "llm":
        if not str(c.get("prompt", "")).strip():
            out.append(issue("Claude LLM node has an empty prompt"))
        if c.get("output", "json") not in ("json", "text"):
            out.append(issue("LLM output must be 'json' or 'text'"))
    elif t == "validator":
        rules = c.get("rules") or []
        if not rules:
            out.append(issue("Validator must declare at least one field rule"))
        for r in rules:
            if not r.get("field"):
                out.append(issue("Validator rule is missing a field name"))
            if r.get("type", "string") not in N.VALIDATOR_TYPES:
                out.append(issue(f"Validator field '{r.get('field')}' has unsupported type '{r.get('type')}'"))
    elif t == "condition":
        if not str(c.get("field", "")).strip():
            out.append(issue("Condition is missing a field path"))
        if c.get("operator") not in N.CONDITION_OPS:
            out.append(issue(f"Condition operator '{c.get('operator')}' is not supported"))
    elif t == "transform":
        ops = c.get("ops") or []
        if not ops:
            out.append(issue("Transform must declare at least one operation"))
        for op in ops:
            if op.get("op") not in N.TRANSFORM_OPS:
                out.append(issue(f"Transform operation '{op.get('op')}' is not supported"))
            elif op["op"] in ("pick", "omit") and not op.get("fields"):
                out.append(issue(f"Transform '{op['op']}' needs a field list"))
            elif op["op"] in ("set", "rename", "to_number", "uppercase", "lowercase") and not (
                    op.get("field") or op.get("from")):
                out.append(issue(f"Transform '{op['op']}' is missing a target field"))
            elif op["op"] == "rename" and not op.get("to"):
                out.append(issue("Transform 'rename' needs a destination field"))
    elif t == "http":
        url = str(c.get("url", ""))
        if not url:
            out.append(issue("HTTP Request node has no URL"))
        elif not (url.startswith("mock://") or url.startswith("https://")):
            out.append(issue("HTTP URL must use mock:// or https://"))
    elif t == "failure_sim":
        if c.get("failure") not in ("missing_field", "wrong_type", "wrong_value", "malformed_json", "empty_response",
                                    "http_500", "timeout", "fail_validation"):
            out.append(issue("Failure Simulator has an unsupported failure kind"))
    elif t == "input":
        if not isinstance(c.get("sample"), (dict, list)):
            out.append(issue("Input node sample payload must be JSON object or array"))
    return out


def validate_graph(wf: dict) -> list[dict]:
    nlist, elist = wf.get("nodes") or [], wf.get("edges") or []
    issues: list[dict] = []
    ids = [n.get("id") for n in nlist]
    dups = {i for i in ids if ids.count(i) > 1}
    for d in dups:
        issues.append({"node_id": d, "message": f"Duplicate node id '{d}'", "severity": "error", "code": "graph"})
    by_id = {n["id"]: n for n in nlist if n.get("id")}
    for n in nlist:
        issues.extend(_node_issues(n))
    for e in elist:
        s, t = e.get("source"), e.get("target")
        if s not in by_id or t not in by_id:
            issues.append({"edge_id": e.get("id"), "message": "Edge references a node that does not exist",
                           "severity": "error", "code": "graph"})
            continue
        if s == t:
            issues.append({"edge_id": e.get("id"), "message": "Self-connections are not allowed", "severity": "error",
                           "code": "graph"})
        stype = by_id[s].get("type")
        handle = e.get("sourceHandle") or "out"
        allowed = OUTPUT_HANDLES.get(stype, OUTPUT_HANDLES["default"]) | {ERROR_HANDLE}
        if handle not in allowed:
            issues.append({"edge_id": e.get("id"), "node_id": s,
                           "message": f"Connection from '{by_id[s].get('label', s)}' uses invalid output '{handle}'",
                           "severity": "error", "code": "graph"})
    if not nlist:
        issues.append({"message": "Workflow has no nodes", "severity": "error", "code": "graph"})
    if not any(n.get("type") == "input" for n in nlist):
        issues.append({"message": "Workflow needs an Input node to start execution", "severity": "error",
                       "code": "graph"})
    if not any(n.get("type") == "output" for n in nlist):
        issues.append({"message": "Workflow needs an Output node", "severity": "error", "code": "graph"})
    # cycle detection (Kahn)
    indeg = {i: 0 for i in by_id}
    adj = defaultdict(list)
    for e in elist:
        if e.get("source") in by_id and e.get("target") in by_id:
            indeg[e["target"]] += 1
            adj[e["source"]].append(e["target"])
    q = deque(i for i, d in indeg.items() if d == 0)
    seen = 0
    while q:
        cur = q.popleft()
        seen += 1
        for nx in adj[cur]:
            indeg[nx] -= 1
            if indeg[nx] == 0:
                q.append(nx)
    if seen != len(by_id):
        issues.append({"message": "Workflow contains a cycle — cycles are not supported", "severity": "error",
                       "code": "cycle"})
    # unreachable nodes (warning)
    reach = set()
    starts = [i for i, n in by_id.items() if n.get("type") == "input"]
    dq = deque(starts)
    while dq:
        cur = dq.popleft()
        if cur in reach:
            continue
        reach.add(cur)
        for nx in adj[cur]:
            dq.append(nx)
    for i, n in by_id.items():
        if i not in reach and n.get("type") != "input":
            issues.append({"node_id": i, "node_label": n.get("label"), "severity": "warning", "code": "unreachable",
                           "message": f"'{n.get('label', i)}' is not reachable from the Input node"})
    return issues


def assert_valid(wf: dict) -> None:
    issues = [i for i in validate_graph(wf) if i["severity"] == "error"]
    if issues:
        raise GraphInvalid(issues)


# ------------------------------------------------------------------ execution
def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def execute(wf: dict, payload: Any, *, llm_mode: str = "mock", scenario: dict | None = None,
            workflow_version: int | None = None, metadata: dict | None = None) -> dict:
    """Run a workflow deterministically. Returns a full trace record.

    scenario (WhatIf): {name, target_node_id, kind, field, expect_failure: bool, expected: str, ...}
    """
    started = time.perf_counter()
    nlist, elist = wf.get("nodes") or [], wf.get("edges") or []
    by_id = {n["id"]: n for n in nlist}
    out_edges = defaultdict(list)
    for e in elist:
        out_edges[e["source"]].append(e)
    in_edges = defaultdict(list)
    for e in elist:
        in_edges[e["target"]].append(e)

    # deterministic topological order
    indeg = {i: 0 for i in by_id}
    for e in elist:
        if e.get("source") in by_id and e.get("target") in by_id:
            indeg[e["target"]] += 1
    queue = deque(sorted([i for i, d in indeg.items() if d == 0]))
    order: list[str] = []
    while queue:
        cur = queue.popleft()
        order.append(cur)
        for e in sorted(out_edges[cur], key=lambda x: x.get("id", "")):
            if e["target"] in indeg:
                indeg[e["target"]] -= 1
                if indeg[e["target"]] == 0:
                    queue.append(e["target"])

    steps: list[dict] = []
    state: dict[str, dict] = {}       # node_id -> {"output", "handle", "status"}
    queue2 = deque(sorted([i for i, n in by_id.items() if n.get("type") == "input"]))
    queued = set(queue2)
    unhandled_failure = False
    handled_failure = False
    outputs: list[dict] = []
    scenario_target = (scenario or {}).get("target_node_id")

    while queue2:
        nid = queue2.popleft()
        node = by_id[nid]
        # gather active inbound edges
        active_inputs = [
            (e, state[e["source"]]) for e in in_edges[nid]
            if e["source"] in state and state[e["source"]]["status"] in ("succeeded", "failed")
            and _edge_active(e, state[e["source"]])
        ]
        is_entry = node.get("type") == "input"
        merged_meta: dict = {}
        if not active_inputs and not is_entry:
            state[nid] = {"status": "skipped", "handle": None, "output": None, "reason": "no active incoming path"}
            steps.append(_step(node, "skipped", 0.0, None, None, meta={"reason": "No active incoming path"},
                               inserted=len(steps)))
            continue
        if is_entry:
            inp = payload
        else:
            # deterministic merge: use the lowest-id active upstream edge
            merged = sorted(active_inputs, key=lambda x: (x[0].get("id", ""), x[0]["source"]))
            inp = merged[0][1]["output"]
            if len(merged) > 1:
                merged_meta["merged_from"] = [e["source"] for e, _ in merged]
        ctx = N.Ctx(llm_mode=llm_mode)
        if scenario_target == nid and scenario:
            ctx.fault = {"kind": scenario.get("kind"), "field": scenario.get("field")}
        t0 = time.perf_counter()
        status, result, err, meta = "succeeded", None, None, dict(merged_meta)
        try:
            result = N.EXECUTORS[node.get("type")](node.get("config") or {}, inp, ctx)
            meta = dict(result.meta)
        except NodeError as e:
            status = "failed"
            err = e
            meta = {k: v for k, v in (e.details or {}).items() if k in ("errors", "checked_fields", "status_code",
                                                                       "body", "raw_output", "position", "timeout_ms")}
        duration = round((time.perf_counter() - t0) * 1000, 2)
        if err is not None and err.duration_ms is not None:
            duration = err.duration_ms
        if ctx.fault_notes:
            meta.setdefault("scenario_fault", {"kind": ctx.fault["kind"], "applied": ctx.fault_applied,
                                               "notes": ctx.fault_notes})
        node_output = result.output if result else None
        state[nid] = {
            "status": status,
            "handle": (result.handle if result else ERROR_HANDLE),
            # on failure, downstream error handlers receive the last-known-good input
            "output": node_output if status == "succeeded" else inp,
            "error": err.to_dict() if err else None,
        }
        steps.append(_step(node, status, duration, inp, node_output if status == "succeeded" else None, err=err,
                           meta=meta, handle=state[nid]["handle"]))
        if status == "succeeded" and node.get("type") == "output":
            outputs.append({"node_id": nid, "label": node.get("label"), "value": node_output,
                            "outcome": meta.get("outcome", "success")})

        # schedule successors
        if status == "failed":
            error_edges = [e for e in out_edges[nid] if (e.get("sourceHandle") or "out") == ERROR_HANDLE]
            if error_edges:
                handled_failure = True
            else:
                unhandled_failure = True
            succ = error_edges
        else:
            h = state[nid]["handle"]
            succ = [e for e in out_edges[nid] if (e.get("sourceHandle") or "out") == h]
        for e in sorted(succ, key=lambda x: x.get("id", "")):
            tid = e["target"]
            if tid in by_id and tid not in queued:
                queued.add(tid)
                queue2.append(tid)

    # nodes never queued => skipped
    queued_ids = {s["node_id"] for s in steps}
    for nid in order:
        if nid not in queued_ids:
            steps.append(_step(by_id[nid], "skipped", 0.0, None, None,
                               meta={"reason": "Unreachable along this execution path"}, inserted=len(steps)))

    status = "failed" if unhandled_failure or not outputs else ("degraded" if handled_failure else "succeeded")
    total_ms = round((time.perf_counter() - started) * 1000, 2)
    trace = {
        "execution_id": _new_id("exec"),
        "workflow_id": wf.get("id"),
        "workflow_name": wf.get("name"),
        "workflow_version": workflow_version if workflow_version is not None else wf.get("version", 1),
        "status": status,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": total_ms,
        "llm_mode": llm_mode,
        "scenario": scenario,
        "steps": steps,
        "outputs": outputs,
        "summary": {
            "nodes_executed": sum(1 for s in steps if s["status"] in ("succeeded", "failed")),
            "nodes_succeeded": sum(1 for s in steps if s["status"] == "succeeded"),
            "nodes_failed": sum(1 for s in steps if s["status"] == "failed"),
            "nodes_skipped": sum(1 for s in steps if s["status"] == "skipped"),
            "failed_nodes": [s["node_id"] for s in steps if s["status"] == "failed"],
            "handled_failure": handled_failure,
            "metadata": metadata or {},
        },
    }
    return trace


def _edge_active(e: dict, src_state: dict) -> bool:
    h = e.get("sourceHandle") or "out"
    if src_state["status"] == "failed":
        return h == ERROR_HANDLE
    return h == src_state["handle"]


def _step(node: dict, status: str, duration_ms: float, inp: Any, out: Any, *, err: NodeError | None = None,
          meta: dict | None = None, handle: str | None = None, inserted: int = 0) -> dict:
    return {
        "node_id": node["id"],
        "label": node.get("label") or node.get("type"),
        "type": node.get("type"),
        "status": status,
        "duration_ms": duration_ms,
        "handle": handle,
        "input": redact(inp),
        "output": redact(out),
        "error": err.to_dict() if err else None,
        "meta": redact(meta or {}),
        "simulated": bool(err.simulated) if err else False,
        "order": inserted,
    }
