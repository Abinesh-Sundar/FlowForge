import json
import os

import pytest

os.environ["FLOWFORGE_FAST"] = "1"
os.environ.setdefault("FLOWFORGE_DB", os.path.join(os.path.dirname(__file__), "test_flowforge.db"))

from flowforge import doctor, graph, nodes, redact, scenarios, seed  # noqa: E402
from flowforge.errors import GraphInvalid, NodeError  # noqa: E402


def run(payload=seed.GOOD_PAYLOAD, scenario=None):
    return graph.execute(seed.DEMO_WORKFLOW, payload, scenario=scenario)


def test_validation_passes_for_demo_workflow():
    assert [i for i in graph.validate_graph(seed.DEMO_WORKFLOW) if i["severity"] == "error"] == []


def test_cycle_and_dangling_edge_rejected():
    wf = json.loads(json.dumps(seed.DEMO_WORKFLOW))
    wf["edges"].append({"id": "cx", "source": "n_condition", "target": "n_llm", "sourceHandle": "true"})
    wf["edges"].append({"id": "dx", "source": "n_input", "target": "missing", "sourceHandle": "out"})
    codes = {i["code"] for i in graph.validate_graph(wf)}
    assert "cycle" in codes and "graph" in codes
    with pytest.raises(GraphInvalid):
        graph.assert_valid(wf)


def test_invalid_source_handle_rejected():
    wf = json.loads(json.dumps(seed.DEMO_WORKFLOW))
    wf["edges"][0]["sourceHandle"] = "true"  # input nodes have no 'true' handle
    assert any(i["code"] == "graph" for i in graph.validate_graph(wf))


def test_baseline_execution_degrades_through_error_handler():
    t = run()
    assert t["status"] == "degraded"
    failed = [s for s in t["steps"] if s["status"] == "failed"]
    assert failed[0]["node_id"] == "n_validator"
    assert failed[0]["error"]["type"] == "validation_failed"
    assert t["outputs"][0]["outcome"] == "error"
    assert not any(s["simulated"] for s in failed), "baseline failure is a real defect, not a simulation"


def test_doctor_fix_is_verified_by_regression():
    wf = seed.DEMO_WORKFLOW
    trace = run()
    diagnosis = doctor.diagnose_deterministic(trace, wf)
    assert diagnosis["proposals"], "doctor should propose a fix"
    before = doctor.run_regression(wf, seed.GOOD_PAYLOAD)
    repaired = doctor.apply_proposal(wf, diagnosis["proposals"][0])
    after = doctor.run_regression(repaired, seed.GOOD_PAYLOAD)
    cmp = doctor.compare(before, after)
    assert after["passed"] == after["total"], [r for r in after["results"] if not r["passed"]]
    assert cmp["improved"] and not cmp["regressed"]
    # the original workflow object must be untouched
    assert wf["nodes"][1]["config"]["prompt"] == seed.VAGUE_PROMPT


def test_apply_proposal_rejects_unknown_node():
    bad = {"apply": [{"op": "set_config", "node_id": "nope", "path": "prompt", "value": "x"}]}
    with pytest.raises(ValueError):
        doctor.apply_proposal(seed.DEMO_WORKFLOW, bad)


@pytest.mark.parametrize("scenario", scenarios.build_catalog(seed.DEMO_WORKFLOW), ids=lambda s: s["id"])
def test_every_scenario_is_deterministic_and_passes(scenario):
    sc = {k: scenario.get(k) for k in ("id", "name", "kind", "target_node_id", "field", "expected")}
    a = graph.execute(seed.DEMO_WORKFLOW, seed.GOOD_PAYLOAD, scenario=sc)
    b = graph.execute(seed.DEMO_WORKFLOW, seed.GOOD_PAYLOAD, scenario=sc)
    verdict = scenarios.evaluate(a, sc["expected"])
    # A scenario blocked by an earlier (pre-existing) failure is reported as blocked, never as a silent pass.
    assert verdict["passed"] or verdict["blocked"], verdict
    assert [(s["node_id"], s["status"]) for s in a["steps"]] == [(s["node_id"], s["status"]) for s in b["steps"]]
    assert a["outputs"] == b["outputs"]


def test_diagnosis_never_raises_for_any_trace():
    """Regression: a trace step must never be mistaken for a workflow node."""
    wf = seed.DEMO_WORKFLOW
    traces = [graph.execute(wf, seed.GOOD_PAYLOAD)]
    for sc in scenarios.build_catalog(wf):
        traces.append(graph.execute(wf, seed.GOOD_PAYLOAD,
                                    scenario={k: sc.get(k) for k in ("id", "name", "kind", "target_node_id",
                                                                      "field", "expected")}))
    for t in traces:
        d = doctor.diagnose_deterministic(t, wf)
        assert "summary" in d and isinstance(d["proposals"], list)
        for p in d["proposals"]:
            # every proposal must target a real node and be applicable
            assert p["target_node_id"] in {n["id"] for n in wf["nodes"]}
            doctor.apply_proposal(wf, p)


def test_mock_llm_is_deterministic():
    assert nodes.llm.mock_extract("Return JSON", seed.GOOD_PAYLOAD) == nodes.llm.mock_extract(
        "Return JSON", seed.GOOD_PAYLOAD)


def test_malformed_json_error_is_reported():
    with pytest.raises(NodeError) as e:
        nodes.llm.parse_json_text('{"a": 1, "b"')
    assert e.value.type == "malformed_json"


def test_validator_rules():
    rules = [{"field": "amount", "type": "number", "min": 1}]
    assert nodes.validate_rules(rules, {"amount": 5}) == []
    errs = nodes.validate_rules(rules, {"amount": "5"})
    assert errs[0]["code"] == "type"
    assert nodes.validate_rules(rules, {})[0]["code"] == "missing"
    assert nodes.validate_rules(rules, {"amount": 0.5})[0]["code"] == "min"
    assert nodes.validate_rules(rules, {"amount": True})[0]["code"] == "type"


def test_http_is_restricted():
    with pytest.raises(NodeError):
        nodes._check_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(NodeError):
        nodes._check_url("https://example.com/hook")
    assert nodes._check_url("mock://erp/invoices").scheme == "mock"


def test_redaction():
    out = redact.redact({"api_key": "sk-ant-abcdefghijklmnop", "nested": {"password": "hunter2"},
                         "document": "Bearer abcdefghijklmnop"})
    assert out["api_key"] == "[REDACTED]"
    assert out["nested"]["password"] == "[REDACTED]"
    assert "abcdefghijklmnop" not in out["document"]


def test_token_metrics_survive_redaction_but_tokens_do_not():
    out = redact.redact({"usage": {"input_tokens": 321, "output_tokens": 45, "max_tokens": 4096},
                         "token": "sk-live-secret", "api_key": "sk-ant-xyz"})
    assert out["usage"] == {"input_tokens": 321, "output_tokens": 45, "max_tokens": 4096}
    assert out["token"] == "[REDACTED]" and out["api_key"] == "[REDACTED]"


def test_openrouter_response_is_parsed(monkeypatch):
    """OpenRouter path must map model ids, send the key server-side, and report usage."""
    import json as _json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = _json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.update(model=body["model"], auth=self.headers.get("Authorization"))
            payload = _json.dumps({"id": "gen", "model": "anthropic/claude-opus-5.5", "choices": [
                {"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 40}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    srv = HTTPServer(("127.0.0.1", 879), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setattr(nodes.llm, "OPENROUTER_URL", "http://127.0.0.1:879/v1/chat/completions")
        r = nodes.llm.call_model("claude-opus-5-5", "extract", {"a": 1})
        assert seen["model"] == "anthropic/claude-opus-5.5"
        assert seen["auth"] == "Bearer sk-or-test"
        assert r["usage"] == {"input_tokens": 300, "output_tokens": 40}
    finally:
        srv.shutdown()


def test_openai_response_is_parsed(monkeypatch):
    """OpenAI path must map Claude model ids to gpt-4o-mini, send the key server-side, enforce low max_tokens, and report usage."""
    import json as _json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = _json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.update(
                model=body["model"],
                auth=self.headers.get("Authorization"),
                max_tokens=body.get("max_tokens"),
                temperature=body.get("temperature"),
                messages=body.get("messages"),
                response_format=body.get("response_format"),
            )
            payload = _json.dumps({
                "id": "chatcmpl-test",
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 15},
            }).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    srv = HTTPServer(("127.0.0.1", 880), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("OPENROUTER_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test-key")
        monkeypatch.setattr(nodes.llm, "OPENAI_URL", "http://127.0.0.1:880/v1/chat/completions")
        r = nodes.llm.call_model("claude-opus-5-5", "extract json fields", {"invoice_no": "INV-1"})
        assert seen["model"] == "gpt-4o-mini", "must use smallest OpenAI model"
        assert seen["auth"] == "Bearer sk-openai-test-key"
        assert seen["max_tokens"] <= 1000, "must limit max_tokens to consume minimal tokens"
        assert seen["temperature"] == 0.0
        assert seen["response_format"] == {"type": "json_object"}
        assert r["text"] == '{"ok": true}'
        assert r["model"] == "gpt-4o-mini"
        assert r["usage"] == {"input_tokens": 120, "output_tokens": 15}
    finally:
        srv.shutdown()


def test_provider_selection_any_of_three(monkeypatch):
    """Any of the three API keys is accepted when provided."""
    # Only OpenAI key
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert nodes.llm.provider() == "openai"
    assert nodes.llm.live_available() is True
    assert nodes.llm.provider_label() == "OpenAI"
    assert nodes.llm.active_model("claude-opus-5-5") == "gpt-4o-mini"

    # Only Anthropic key
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    assert nodes.llm.provider() == "anthropic"
    assert nodes.llm.live_available() is True

    # Only OpenRouter key
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    assert nodes.llm.provider() == "openrouter"
    assert nodes.llm.live_available() is True

    # Explicit FLOWFORGE_PROVIDER override
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    monkeypatch.setenv("FLOWFORGE_PROVIDER", "openai")
    assert nodes.llm.provider() == "openai"
    monkeypatch.setenv("FLOWFORGE_PROVIDER", "openrouter")
    assert nodes.llm.provider() == "openrouter"
    monkeypatch.setenv("FLOWFORGE_PROVIDER", "anthropic")
    assert nodes.llm.provider() == "anthropic"


def test_openai_token_cost_estimation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # gpt-4o-mini: $0.15/1M input, $0.60/1M output
    cost = nodes.llm.estimate_cost("claude-opus-5-5", 1000, 500)
    assert cost == round((1000 * 0.15 + 500 * 0.60) / 1_000_000, 6)


def test_provider_selection_prefers_anthropic(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENROUTER_API_KEY", "b")
    assert nodes.llm.provider() == "anthropic"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert nodes.llm.provider() == "openrouter"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert nodes.llm.provider() is None and not nodes.llm.live_available()


def test_env_file_loader_does_not_override_real_env(tmp_path, monkeypatch):
    from flowforge import config
    f = tmp_path / ".env"
    f.write_text("FLOWFORGE_TEST_A=from_file\nFLOWFORGE_TEST_B=from_file\n", encoding="utf-8")
    monkeypatch.setenv("FLOWFORGE_TEST_B", "from_shell")
    monkeypatch.delenv("FLOWFORGE_TEST_A", raising=False)
    config.load_env(f)
    import os as _os
    assert _os.environ["FLOWFORGE_TEST_A"] == "from_file"
    assert _os.environ["FLOWFORGE_TEST_B"] == "from_shell"


def test_failed_node_never_leaks_secrets_into_trace():
    wf = json.loads(json.dumps(seed.DEMO_WORKFLOW))
    wf["nodes"][1]["config"]["prompt"] = "Return JSON. token=sk-ant-supersecretvalue123"
    t = graph.execute(wf, seed.GOOD_PAYLOAD)
    blob = json.dumps(t)
    assert "sk-ant-supersecretvalue123" not in blob


def test_unknown_node_type_rejected():
    wf = json.loads(json.dumps(seed.DEMO_WORKFLOW))
    wf["nodes"][1] = dict(wf["nodes"][1], type="python_exec")
    with pytest.raises(GraphInvalid):
        graph.assert_valid(wf)


def test_app_imports_when_run_from_inside_the_package():
    """`python -m uvicorn app:app` from backend/flowforge/ must work, not just flowforge.app:app."""
    import subprocess
    import sys
    from pathlib import Path

    pkg_dir = Path(__file__).resolve().parent.parent / "flowforge"
    r = subprocess.run([sys.executable, "-c", "import app; print(app.app.title)"],
                       cwd=pkg_dir, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "FlowForge AI" in r.stdout


def test_root_serves_the_ui_or_build_instructions():
    from fastapi.testclient import TestClient
    from flowforge.app import app

    r = TestClient(app).get("/")
    assert r.status_code == 200
    # Either the built SPA (nav index) or the "build the frontend" instructions — never a bare 404.
    assert "<html" in r.text.lower()
