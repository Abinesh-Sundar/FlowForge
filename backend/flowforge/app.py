"""FastAPI application: FlowForge builder, WhatIf AI simulation, Agent Black Box traces, Workflow Doctor."""
from __future__ import annotations

# Allow `uvicorn app:app` from inside this directory as well as `uvicorn flowforge.app:app` from backend/.
# Without this, relative imports below raise "attempted relative import with no known parent package".
if __package__ in (None, ""):
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    __package__ = "flowforge"

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import doctor, llm, scenarios, seed, store
from .errors import GraphInvalid
from .graph import execute, validate_graph

app = FastAPI(title="FlowForge AI", version="1.0.0")
# Any localhost port is allowed so the Vite dev server works on 5173, 5174 (when 5173 is taken), etc.
app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
                   allow_methods=["*"], allow_headers=["*"])

# The built UI (frontend/dist) is served from the same origin as the API when it exists, so the whole app
# runs on one port with no dev server. In dev, Vite serves the UI and proxies /api here instead.
_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


# ------------------------------------------------------------------ models
class Node(BaseModel):
    id: str
    type: str
    label: str | None = None
    position: dict[str, float] = {}
    config: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: str | None = "out"


class Workflow(BaseModel):
    id: str
    name: str = "Untitled workflow"
    description: str = ""
    version: int = 1
    nodes: list[Node]
    edges: list[Edge]


class RunRequest(BaseModel):
    workflow: Workflow
    payload: Any = None
    llm_mode: Literal["mock", "live"] = "mock"
    scenario_id: str | None = None
    persist: bool = True


class ScenarioRequest(BaseModel):
    workflow: Workflow
    scenario_id: str
    payload: Any = None
    llm_mode: Literal["mock", "live"] = "mock"
    persist: bool = True


class DiagnoseRequest(BaseModel):
    workflow: Workflow
    execution_id: str
    live: bool = False


class ApplyRequest(BaseModel):
    workflow: Workflow
    proposal: dict[str, Any]
    save: bool = True


class RegressionRequest(BaseModel):
    workflow: Workflow
    payload: Any = None
    llm_mode: Literal["mock", "live"] = "mock"


class VerifyRequest(BaseModel):
    original_workflow: Workflow
    repaired_workflow: Workflow
    payload: Any = None
    llm_mode: Literal["mock", "live"] = "mock"


def _wf(model: Workflow) -> dict:
    return model.model_dump()


def _default_payload(wf: dict) -> Any:
    n = next((n for n in wf["nodes"] if n["type"] == "input"), None)
    return (n or {}).get("config", {}).get("sample") or {}


def _run(wf: dict, payload, llm_mode, scenario=None, persist=True) -> dict:
    trace = execute(wf, payload, llm_mode=llm_mode, scenario=scenario, workflow_version=wf.get("version", 1))
    if persist:
        store.save_execution(trace)
    return trace


@app.on_event("startup")
def startup() -> None:
    store.init()
    if not store.get_workflow(seed.DEMO_WORKFLOW["id"]):
        store.save_workflow(seed.DEMO_WORKFLOW, note="Seeded demo workflow")


# ------------------------------------------------------------------ UI (built frontend)
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> Any:
    """Serve the built UI. If it has not been built yet, explain how to start it instead of a bare 404."""
    if (_DIST / "index.html").exists():
        return FileResponse(_DIST / "index.html")
    return HTMLResponse(
        """<!doctype html><meta charset="utf-8"><title>FlowForge AI</title>
        <body style="font:14px/1.6 system-ui;background:#0b0d10;color:#e6e9ee;padding:40px;max-width:760px;margin:auto">
        <h2 style="margin-bottom:4px">FlowForge AI backend is running</h2>
        <p style="color:#97a1b0">The API is live at <code>/api/health</code>, but the frontend has not been built yet.</p>
        <p>Start it in one of these two ways:</p>
        <ol style="color:#e6e9ee">
          <li><b>Development</b> (hot reload): <code>cd frontend &amp;&amp; npm run dev</code> &rarr;
              open <a style="color:#6aa6ff" href="http://localhost:5173">http://localhost:5173</a></li>
          <li><b>Single port</b>: <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>,
              then reload this page</li>
        </ol>
        <p><a style="color:#6aa6ff" href="/docs">API documentation &rarr;</a></p></body>""",
        status_code=200,
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Any:
    icon = _DIST / "favicon.ico"
    if icon.exists():
        return FileResponse(icon)
    return HTMLResponse(status_code=204)


if (_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "llm_live_available": llm.live_available(),
            # Mock stays the default so the deterministic demo is identical with or without an API key.
            # Live is an explicit opt-in (the Mock / Claude live toggle), unless FLOWFORGE_DEFAULT_LIVE=1.
            "llm_mode_default": ("live" if os.environ.get("FLOWFORGE_DEFAULT_LIVE") == "1" and llm.live_available()
                                 else "mock"),
            "provider": llm.provider_label(),
            "model": os.environ.get("FLOWFORGE_MODEL", llm.DEFAULT_MODEL),
            "model_live": llm.active_model(os.environ.get("FLOWFORGE_MODEL", llm.DEFAULT_MODEL)),
            "http_allowlist": [h for h in os.environ.get("FLOWFORGE_HTTP_ALLOWLIST", "").split(",") if h]}


# ------------------------------------------------------------------ workflows
@app.get("/api/workflows")
def workflows() -> list[dict]:
    return store.list_workflows()


@app.get("/api/workflows/{wid}")
def workflow(wid: str) -> dict:
    wf = store.get_workflow(wid)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return wf


@app.post("/api/workflows")
def save(wf: Workflow, note: str = "manual save") -> dict:
    wf.version = (store.get_workflow(wf.id) or {}).get("version", 1)
    res = store.save_workflow(_wf(wf), note)
    return res


@app.get("/api/workflows/{wid}/versions")
def versions(wid: str) -> list[dict]:
    return store.list_versions(wid)


@app.get("/api/workflows/{wid}/versions/{version}")
def version(wid: str, version: int) -> dict:
    v = store.get_version(wid, version)
    if not v:
        raise HTTPException(404, "Version not found")
    return v


@app.post("/api/workflows/validate")
def validate(wf: Workflow) -> dict:
    issues = validate_graph(_wf(wf))
    return {"valid": not any(i["severity"] == "error" for i in issues), "issues": issues}


@app.post("/api/workflows/{wid}/reset")
def reset(wid: str) -> dict:
    if wid != seed.DEMO_WORKFLOW["id"]:
        raise HTTPException(404, "Only the demo workflow has a reset target")
    store.restore_workflow(seed.DEMO_WORKFLOW, note="reset to demo baseline")
    return store.get_workflow(wid)


# ------------------------------------------------------------------ execution
@app.post("/api/run")
def run(req: RunRequest) -> dict:
    wf = _wf(req.workflow)
    payload = req.payload if req.payload is not None else _default_payload(wf)
    scenario = None
    if req.scenario_id:
        scenario = scenarios.find_scenario(wf, req.scenario_id)
        if not scenario:
            raise HTTPException(400, f"Unknown scenario '{req.scenario_id}'")
        scenario = {k: scenario.get(k) for k in ("id", "name", "kind", "target_node_id", "field", "expected",
                                                 "description")}
    try:
        trace = _run(wf, payload, req.llm_mode, scenario, req.persist)
    except GraphInvalid as e:
        raise HTTPException(422, {"message": "Workflow graph is invalid", "issues": e.issues})
    return trace


# ------------------------------------------------------------------ WhatIf AI
@app.post("/api/scenarios")
def catalog(wf: Workflow) -> list[dict]:
    return scenarios.build_catalog(_wf(wf))


@app.post("/api/simulate")
def simulate(req: ScenarioRequest) -> dict:
    wf = _wf(req.workflow)
    sc = scenarios.find_scenario(wf, req.scenario_id)
    if not sc:
        raise HTTPException(400, f"Unknown scenario '{req.scenario_id}'")
    payload = req.payload if req.payload is not None else _default_payload(wf)
    scenario = {k: sc.get(k) for k in ("id", "name", "kind", "target_node_id", "field", "expected", "description")}
    try:
        trace = _run(wf, payload, req.llm_mode, scenario, req.persist)
    except GraphInvalid as e:
        raise HTTPException(422, {"message": "Workflow graph is invalid", "issues": e.issues})
    verdict = scenarios.evaluate(trace, sc["expected"])
    checks = verdict["checks"] + scenarios.activity_checks(trace)
    result = {"scenario": {**sc, "target_label": next(
                (n.get("label") for n in wf["nodes"] if n["id"] == sc["target_node_id"]), sc["target_node_id"])},
              "expected_behavior": sc["expected"]["text"],
              "actual_behavior": verdict["actual_behavior"],
              "passed": verdict["passed"], "blocked": verdict["blocked"],
              "blocked_reason": verdict["blocked_reason"], "checks": checks,
              "trace": trace,
              "distinction": "Failure injected by WhatIf AI through the real node code path (marked simulated "
                             "where the node did not perform its real work)."}
    return result


# ------------------------------------------------------------------ Agent Black Box
@app.get("/api/executions")
def executions(workflow_id: str | None = None, limit: int = 25) -> list[dict]:
    return store.list_executions(workflow_id, limit)


@app.get("/api/executions/{eid}")
def execution(eid: str) -> dict:
    t = store.get_execution(eid)
    if not t:
        raise HTTPException(404, "Execution not found")
    return t


# ------------------------------------------------------------------ Doctor
@app.post("/api/diagnose")
def diagnose(req: DiagnoseRequest) -> dict:
    trace = store.get_execution(req.execution_id)
    if not trace:
        raise HTTPException(404, "Execution not found")
    return doctor.diagnose(trace, _wf(req.workflow), live=req.live)


@app.post("/api/apply")
def apply(req: ApplyRequest) -> dict:
    p = req.proposal
    if not p.get("apply"):
        raise HTTPException(400, "Proposal has no applicable changes")
    try:
        repaired = doctor.apply_proposal(_wf(req.workflow), p)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Could not apply proposal: {e}")
    repaired["description"] = (req.workflow.description + f" [doctor fix: {p.get('id')}]").strip()
    saved = store.save_workflow(repaired, note=f"AI Doctor fix: {p.get('title')}") if req.save else None
    return {"workflow": repaired, "version": (saved or {}).get("version"), "applied": p.get("id"),
            "message": "Applied to a new workflow version. Regression tests must pass before you rely on it."}


@app.post("/api/regression")
def regression(req: RegressionRequest) -> dict:
    wf = _wf(req.workflow)
    payload = req.payload if req.payload is not None else _default_payload(wf)
    out = doctor.run_regression(wf, payload, llm_mode=req.llm_mode)
    for r in out["results"]:
        if r.get("trace"):
            store.save_execution(r["trace"])
            r["trace"] = {k: r["trace"][k] for k in ("execution_id", "status", "duration_ms", "steps")}
    return out


@app.post("/api/verify")
def verify(req: VerifyRequest) -> dict:
    orig, rep = _wf(req.original_workflow), _wf(req.repaired_workflow)
    payload = req.payload if req.payload is not None else _default_payload(rep)
    before = doctor.run_regression(orig, payload, llm_mode=req.llm_mode)
    after = doctor.run_regression(rep, payload, llm_mode=req.llm_mode)
    repair_trace = None
    failing = [r for r in after["results"] if not r["passed"]]
    if after["results"]:
        repair_trace = next((r["trace"] for r in after["results"] if r["id"] == "reg-type"), None)
    for r in before["results"] + after["results"]:
        if r.get("trace"):
            store.save_execution(r["trace"])
    cmp = doctor.compare(before, after)
    return {"comparison": cmp, "before": {"passed": before["passed"], "total": before["total"],
                                          "results": [{k: r[k] for k in ("id", "name", "passed", "actual_status")}
                                                      for r in before["results"]]},
            "after": {"passed": after["passed"], "total": after["total"],
                      "results": [{k: r[k] for k in ("id", "name", "passed", "actual_status")}
                                  for r in after["results"]]},
            "repair_execution_id": (repair_trace or {}).get("execution_id"),
            "remaining_failures": [f["name"] for f in failing],
            "ok": cmp["after_passed"] == cmp["total"]}
