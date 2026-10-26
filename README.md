# FlowForge AI

A unified AI workflow engineering platform: visual builder, deterministic failure simulation, execution
observability, and an AI Workflow Doctor that diagnoses, proposes, and *verifies* repairs.

## Quick start

**One port (simplest).** The backend serves the built UI itself, so the whole app lives at one URL.

```bash
cd frontend && npm install && npm run build   # once, and again after frontend changes
cd ../backend
pip install -r requirements.txt
uvicorn flowforge.app:app --reload --port 8000
```

Open http://127.0.0.1:8000 — canvas, API and `/docs` share that origin. Any port works
(`--port 8081` → http://127.0.0.1:8081).

**Two terminals (hot reload while developing).**

```bash
# terminal 1
cd backend && uvicorn flowforge.app:app --reload --port 8000

# terminal 2
cd frontend && npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.
If the backend runs on a different port, point the proxy at it:

```bash
VITE_API_TARGET=http://127.0.0.1:8081 npm run dev
```

> **Note:** `uvicorn app:app` works from inside `backend/flowforge/` as well as `flowforge.app:app`
> from `backend/`. If the UI loads with no data, the API is unreachable — the app says so on screen
> (with a Retry button) instead of showing empty panels behind a spinner.

## Configuration: the `.env` file

Create `backend/.env` (copy `backend/.env.example`). The backend loads it automatically on startup, and real
environment variables always win over the file.

```bash
cp backend/.env.example backend/.env
```

**Have an OpenAI key?** Put it in `OPENAI_API_KEY` — it automatically uses OpenAI's smallest, ultra-fast model (`gpt-4o-mini`) with compact token formatting to minimize token consumption:

```ini
OPENAI_API_KEY=sk-proj-your-key-here
```

**Have an OpenRouter key?** Put it in `OPENROUTER_API_KEY` — that is fully supported:

```ini
OPENROUTER_API_KEY=sk-or-v1-your-key-here
FLOWFORGE_MODEL=claude-opus-5-5
```

The app maps model ids automatically (OpenAI uses `gpt-4o-mini`, OpenRouter maps `claude-opus-5-5` → `anthropic/claude-opus-5.5`) and reports real token usage and estimated cost. Keys are used server-side only and never reach the browser. Whichever of the three keys (Anthropic, OpenAI, or OpenRouter) you provide, FlowForge will use it.

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | no | OpenAI API path. Automatically selects OpenAI's smallest model (`gpt-4o-mini`) and strictly minimizes token consumption. |
| `ANTHROPIC_API_KEY` | no | Native Anthropic SDK path. |
| `OPENROUTER_API_KEY` | no | OpenRouter (OpenAI-compatible) path. Use this if your key is `sk-or-v1-...`. |
| `FLOWFORGE_PROVIDER` | no | Optional explicit override (`openai`, `anthropic`, or `openrouter`) if multiple keys are configured. |
| `OPENROUTER_BASE_URL` | no | Default `https://openrouter.ai/api/v1/chat/completions`. |
| `OPENROUTER_APP_NAME` / `OPENROUTER_APP_URL` | no | Optional attribution headers for the OpenRouter dashboard. |
| `FLOWFORGE_MODEL` | no | Anthropic-style model id (default `claude-opus-5-5`); mapped automatically for OpenAI (`gpt-4o-mini`) and OpenRouter. |
| `FLOWFORGE_HTTP_ALLOWLIST` | no | **SSRF guard.** Comma-separated `https` hosts the HTTP Request node may call, e.g. `api.example.com`. Empty means only `mock://` endpoints. Leave empty for the demo — nothing external is needed. |
| `FLOWFORGE_DB` | no | SQLite path (default `backend/data/flowforge.db`). |
| `FLOWFORGE_DEFAULT_LIVE` | no | Set to `1` to start in live mode when a key exists. Default is the mock model. |

The app always starts on the deterministic mock model, whether or not a key is configured, so the demo
and the regression numbers are identical everywhere. **Live** in the top bar switches to the real
provider for that session (token usage and cost are then shown for real).

## The demo journey (≈60 seconds)

1. **Build** — the seeded *Invoice Intake → ERP Posting* workflow loads on the canvas.
2. **Execute** — press **▶ Run workflow**. The run is `degraded`: the Claude node accepts the model output, the
   Validator rejects `date` (not ISO) and `amount` (a string), and the Error Handler absorbs it.
3. **Observe** — click the failing node in the timeline. The Black Box shows its input, the model's raw output,
   and the exact validation errors.
4. **Diagnose** — open the **Doctor** tab and press *Diagnose this execution*. Evidence cites the failing node,
   the rule violations and the upstream model output.
5. **Approve** — review the prompt-contract diff and approve it. This creates workflow **v2**; v1 is preserved.
6. **Retest & compare** — the 6-check regression suite runs on both versions: **4/6 → 6/6**, with the repaired
   trace available in History.
7. **Simulate** — in **WhatIf AI**, run all scenarios (malformed JSON, missing field, wrong type, ERP 500,
   timeouts, empty responses). Each shows expected vs actual, pass/fail, and its own trace.

## Tests

```bash
cd backend
pytest -q          # 24 tests: engine, validation, scenarios, doctor, redaction, SSRF guard
```

## UI verification

With both servers running and `pip install playwright`:

```bash
python scripts/ui_check.py     # drives the full loop in Chrome, asserts 6/6, fails on console errors
```

## Implemented vs mocked

See [`PLAN.md`](./PLAN.md) §7 for the full matrix. Short version: the engine, validator, simulation, tracing,
persistence, diagnosis and regression comparison are all real; the Claude model, the ERP endpoint, and
simulated latency are mocked unless a key is configured.
