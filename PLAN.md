# FlowForge AI — Plan

FlowForge AI is one platform with three capabilities that share a single workflow model and a single
execution record:

| Capability | Role in the loop |
|---|---|
| **FlowForge** — visual builder | Build / configure the graph and run it |
| **WhatIf AI** — failure simulation | Simulate deterministic failures before trusting the workflow |
| **Agent Black Box** — observability | Observe every run: timeline, node I/O, errors, usage |
| **AI Workflow Doctor** — repair | Diagnose from the trace, propose a fix, get approval, verify by regression |

The central experience is the loop: **Build → Simulate → Execute → Observe → Diagnose → Approve → Retest → Compare**.

## 1. System architecture

```mermaid
flowchart LR
    subgraph Browser["Browser — React + Vite + React Flow"]
        UI["Workflow canvas
        node palette · config drawer
        timeline · inspector"]
        WhatIfUI["WhatIf AI panel"]
        BoxUI["Agent Black Box panel"]
        DocUI["Doctor panel"]
    end
    subgraph API["FastAPI — Python 3.12"]
        R["/api/run · /api/simulate"]
        V["graph.validate_graph()"]
        E["graph.execute() — deterministic engine
        topological order · handles · error edges"]
        S["scenarios.py — fault catalog + expectations"]
        D["doctor.py — diagnosis, apply, regression"]
        L["llm.py — mock extractor / Anthropic SDK"]
        RD["redact.py — secrets masking"]
    end
    DB[("SQLite
    workflows · workflow_versions · executions")]
    Claude["Anthropic API
    (optional, server-side key)"]

    UI --> R
    WhatIfUI --> R
    BoxUI -->|"GET /api/executions"| DB
    DocUI --> D
    R --> V --> E
    S --> E
    E --> RD --> DB
    E -->|"llm_mode=live"| L --> Claude
    D --> E
    D --> L
```

Key decisions:

- **One execution engine.** WhatIf, manual runs and regression tests all call `graph.execute()`. Simulation is
  not a separate fake path — a scenario sets a fault on a target node and the real executor reacts to it.
- **Determinism is a contract.** No node depends on wall-clock randomness. The mock model's output format is
  derived from the prompt text, so prompt fixes can be verified offline.
- **LLM never decides pass/fail.** Scenario verdicts come from comparing the trace to declared expectations.
  The Doctor's diagnosis is a hypothesis; the regression suite is the judge.

## 2. Unified product workflow

```mermaid
flowchart TD
    A["Build / edit graph on the canvas"] --> B{"Validate"}
    B -->|"errors"| A
    B -->|"ok"| C["Run or simulate"]
    C --> D["Trace persisted in SQLite"]
    D --> E["Black Box: timeline + node inspector"]
    E --> F["Doctor: evidence-backed diagnosis"]
    F --> G{"Review proposed change"}
    G -->|"Reject"| E
    G -->|"Approve"| H["New workflow version
    (original preserved)"]
    H --> I["Regression suite: 6 deterministic checks"]
    I --> J["Before / after comparison"]
    J --> E
```

## 3. Example invoice-processing graph

Seeded demo workflow `wf_invoice_demo`: **Input → Claude LLM → Validator → Condition → Output**, plus handler paths.

```mermaid
flowchart LR
    IN["Invoice Input
    JSON: document + source"] --> LLM["Claude Extract
    prompt → JSON object"]
    LLM --> VAL["Invoice Contract
    invoice_number / vendor /
    date / amount"]
    VAL -->|"valid"| COND{"Amount > 100?"}
    VAL -->|"error"| ERR["Error Handler
    outcome: error"]
    COND -->|"true"| HTTP["Post to ERP
    mock://erp/invoices"]
    COND -->|"false"| REV["Manual Review
    outcome: review"]
    HTTP -->|"ok"| OK["Posted
    outcome: success"]
    HTTP -->|"error"| ERR
```

**The baseline defect (intentional, and the demo's starting point).** The seeded prompt is under-specified —
it asks for JSON but never pins field types or formats. The deterministic mock model therefore returns
`date: "03/14/2025"` and `amount: "$1,250.00"` (a string). The Validator rejects both, the run goes `degraded`
through the Error Handler, and the Doctor proposes tightening the prompt contract. After approval, the model
returns ISO dates and a numeric amount, the posting path runs, and regression coverage goes from 4/6 to 6/6.

### Node contracts

| Node | Input | Output | Failure modes |
|---|---|---|---|
| Input | — | sample JSON payload | config invalid |
| Claude LLM | any JSON | parsed JSON (or raw text) | `malformed_json`, `empty_response`, `timeout`, `api_error`, `refusal` |
| Transform | object | object | `transform_error` (missing source field) |
| Validator | object | same object (pass-through) | `validation_failed` with per-field evidence |
| Condition | object | same object, handle `true`/`false` | `condition_error` |
| HTTP Request | object → JSON body | input + `http_response` | `http_error`, `timeout`, `empty_response`, `config_error` (blocked URL) |
| Failure Simulator | object | mutated object | any injected kind |
| Output | any | any, plus `outcome` | — |

Handles: every node has `out`; Condition has `true`/`false`; every non-input/non-output node has an `error`
handle. Connections to unknown handles, self-connections, duplicates and cycles are rejected by
`validate_graph()` before execution.

## 4. Failure simulation and diagnosis sequence

```mermaid
sequenceDiagram
    actor U as Engineer
    participant UI as WhatIf / Doctor panel
    participant API as FastAPI
    participant ENG as Execution engine
    participant DOC as Doctor
    participant DB as SQLite

    U->>UI: Select scenario "LLM returns amount as a string"
    UI->>API: POST /api/simulate {scenario_id}
    API->>ENG: execute(graph, payload, fault={kind:wrong_type, field:amount})
    ENG-->>API: trace (Validator failed · Handler engaged)
    API->>DB: persist trace
    API-->>UI: expected vs actual + pass/fail + trace
    U->>UI: Diagnose this execution
    UI->>API: POST /api/diagnose {execution_id}
    API->>DOC: diagnose(trace, graph)
    DOC-->>UI: evidence + ranked proposals (labelled deterministic or Claude)
    U->>UI: Review diff, Approve
    UI->>API: POST /api/apply {proposal}
    API->>DB: save new workflow version (original kept)
    UI->>API: POST /api/verify {original, repaired}
    API->>ENG: run 6-check suite twice
    API-->>UI: before/after table + repaired trace id
```

## 5. Data model

```mermaid
erDiagram
    WORKFLOWS ||--o{ WORKFLOW_VERSIONS : "has"
    WORKFLOWS ||--o{ EXECUTIONS : "produces"
    WORKFLOWS {
        text id PK
        text name
        text graph "JSON: nodes, edges, name"
        int version
        text created_at
        text updated_at
    }
    WORKFLOW_VERSIONS {
        int id PK
        text workflow_id FK
        int version
        text graph
        text note "e.g. AI Doctor fix: ..."
        text created_at
    }
    EXECUTIONS {
        text id PK
        text workflow_id FK
        int workflow_version
        text status "succeeded | degraded | failed"
        text scenario_id
        text scenario_name
        text llm_mode "mock | live"
        real duration_ms
        text trace "JSON: steps, outputs, summary"
        text created_at
    }
```

## 6. Execution states

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running: node scheduled
    running --> succeeded: output produced
    running --> failed: NodeError raised
    pending --> skipped: no active incoming edge
    succeeded --> [*]
    failed --> [*]
    skipped --> [*]

    state "Run status" as Run {
        [*] --> succeeded: all outputs reached, no failure
        succeeded --> degraded: failure absorbed by an error edge
        degraded --> failed: failure had no error edge, or no output reached
    }
```

Run status is derived, not asserted: `failed` if any failure was unhandled or no Output ran; `degraded` if a
failure was absorbed by an error edge and an Output still ran; otherwise `succeeded`.

## 7. What is real vs. simulated

| Real | Simulated / mocked |
|---|---|
| Graph validation, execution engine, handle routing, cycles | Claude model itself when no `ANTHROPIC_API_KEY` is set |
| Validator semantics, transforms, conditions | Downstream ERP (`mock://erp/invoices`) |
| Fault injection through real node code | Scenario latency (scaled out with `FLOWFORGE_FAST=1` in tests) |
| SQLite persistence, versioning, regression suite | Token usage/cost when the mock model is used (reported as unavailable, never as 0) |

The UI labels every mocked run (`mock model` chip), every mock-backed metric (`n/a`, "not reported"), and every
injected fault (`simulated`).

## 8. Model providers

```mermaid
flowchart LR
    N["Claude LLM node / Doctor"] --> D{"provider()"}
    D -->|"ANTHROPIC_API_KEY set"| A["Anthropic SDK
    messages.create"]
    D -->|"OPENROUTER_API_KEY set"| O["OpenRouter
    /chat/completions"]
    D -->|"no key"| M["Deterministic mock extractor
    (labelled in UI + trace)"]
    A --> T["usage + estimated cost"]
    O --> T
    M --> U["usage: null · cost: null
    shown as n/a, never 0"]
```

`backend/.env` is loaded at package import (`flowforge/config.py`) and never overrides real environment variables.
Anthropic takes precedence when both keys are present.

## 9. Security posture

- `ANTHROPIC_API_KEY` is read only from the server environment; the browser never sees it.
- Traces are passed through `redact.py`: sensitive keys (`api_key`, `token`, `password`, `account_number`, …)
  are masked, and value patterns (Anthropic keys, bearer tokens, IBANs) are replaced before persistence and
  before anything is attached to a Claude diagnosis request.
- HTTP nodes accept only `mock://` URLs or `https://` hosts explicitly listed in `FLOWFORGE_HTTP_ALLOWLIST`;
  DNS results resolving to private, loopback, link-local or reserved addresses are refused, and redirects are
  not followed (SSRF guard).
- No node executes user-supplied code; transforms are a fixed set of declarative operations.
- Applying a Doctor proposal always creates a new version — nothing is deployed or overwritten.

## 10. Roadmap

| Phase | Scope | State |
|---|---|---|
| **P0** | Shell, canvas, node config, engine, WhatIf, Black Box, Doctor, regression compare | ✅ built |
| **P1** | SQLite persistence + version history, token/cost display, scenario catalog, empty/error states | ✅ built |
| P2 | Real integrations, scheduling, collaboration, distributed execution, auth | not started |

### Verification performed

- `pytest` — 24 backend tests (engine, validation, cycles/handles, every scenario, Doctor safety, redaction, SSRF guard).
- `scripts/ui_check.py` — drives the real UI in Chrome via Playwright: loads the canvas, runs the workflow, inspects
  the failing node, runs all WhatIf scenarios, diagnoses, approves the fix, and asserts the regression verdict is
  **6/6 (was 4/6)**, failing on any browser console error. Screenshots land in `screenshots/`.

### Known limitations

- Single-process execution; no queue or distributed workers.
- Workflow versioning is append-only; there is no merge or diff between arbitrary versions.
- Regression suite is the fixed default suite (6 checks), not user-authored.
- Live Claude mode assumes the model can satisfy the JSON contract; if it cannot, the regression suite will
  honestly report a remaining failure.
- The mock model is tailored to the invoice-extraction demo; other prompts return generic JSON derived from
  the payload.
- A WhatIf fault can only be judged where execution reaches its target node. On the un-repaired demo the three
  HTTP scenarios are **blocked** by the validator defect and reported as `blocked`, not as passes or failures.
