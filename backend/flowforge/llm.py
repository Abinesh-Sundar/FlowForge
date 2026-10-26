"""Claude LLM access: a deterministic mock extractor, and the real Anthropic SDK call (server-side key only)."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .errors import NodeError

DEFAULT_MODEL = os.environ.get("FLOWFORGE_MODEL", "claude-opus-5-5")
# USD per 1M tokens (input, output) — used for *estimated* cost only.
PRICING = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.0, 50.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-3.5-turbo": (0.50, 1.50),
}

OPENROUTER_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
# OpenRouter model ids differ from Anthropic's; map the Anthropic id to the equivalent OpenRouter id.
OPENROUTER_MODELS = {
    "claude-opus-5-5": "anthropic/claude-opus-5.5",
    "claude-sonnet-5-5": "anthropic/claude-sonnet-5.5",
    "claude-haiku-5-5": "anthropic/claude-haiku-5.5",
    "claude-fable-5-1": "anthropic/claude-fable-5.1",
}

OPENAI_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
# Smallest OpenAI model configured to consume minimal tokens
OPENAI_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODELS = {
    "claude-opus-5-5": OPENAI_DEFAULT_MODEL,
    "claude-sonnet-5-5": OPENAI_DEFAULT_MODEL,
    "claude-haiku-5-5": OPENAI_DEFAULT_MODEL,
    "claude-fable-5-1": OPENAI_DEFAULT_MODEL,
}


def resolve_openai_model(model: str | None = None) -> str:
    """Map any Claude or default model id to OpenAI's smallest model (gpt-4o-mini)."""
    target = model or os.environ.get("FLOWFORGE_MODEL", DEFAULT_MODEL)
    if target in OPENAI_MODELS:
        return OPENAI_MODELS[target]
    if target.startswith("claude-"):
        return OPENAI_DEFAULT_MODEL
    return target or OPENAI_DEFAULT_MODEL


def active_model(model: str | None = None) -> str:
    """Return the live model id for the active provider."""
    p = provider()
    target = model or os.environ.get("FLOWFORGE_MODEL", DEFAULT_MODEL)
    if p == "openai":
        return resolve_openai_model(target)
    if p == "openrouter":
        return OPENROUTER_MODELS.get(target, target)
    return target


def provider() -> str | None:
    """Which live provider is configured, if any.
    
    If FLOWFORGE_PROVIDER is set, that provider is prioritized if its key is present.
    Otherwise, picks whichever API key is configured among:
    Anthropic > OpenAI > OpenRouter.
    """
    anthropic_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    openrouter_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()

    forced = (os.environ.get("FLOWFORGE_PROVIDER") or "").strip().lower()
    if forced == "anthropic" and anthropic_key:
        return "anthropic"
    if forced == "openai" and openai_key:
        return "openai"
    if forced == "openrouter" and openrouter_key:
        return "openrouter"

    if anthropic_key:
        return "anthropic"
    if openai_key:
        return "openai"
    if openrouter_key:
        return "openrouter"
    return None


def live_available() -> bool:
    return provider() is not None


def provider_label() -> str:
    p = provider()
    return {"anthropic": "Anthropic API", "openai": "OpenAI", "openrouter": "OpenRouter"}.get(p or "", "none (mock)")


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    target = model
    if provider() == "openai":
        target = resolve_openai_model(model)
    p = PRICING.get(target) or PRICING.get(model)
    if not p:
        return None
    return round((input_tokens * p[0] + output_tokens * p[1]) / 1_000_000, 6)


# ---------------------------------------------------------------- mock model
_INV = re.compile(r"(?im)^invoice\s*(?:no\.?|number|#)\s*:\s*(\S+)")
_VENDOR = re.compile(r"(?im)^(?:vendor|from)\s*:\s*(.+?)\s*$")
_DATE = re.compile(r"(?im)^date\s*:\s*(.+?)\s*$")
_TOTAL = re.compile(r"(?im)^(?:total due|amount due|total)\s*:\s*(.+?)\s*$")
_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}


def mock_extract(prompt: str, payload: Any) -> str:
    """Deterministic stand-in for Claude on the invoice-extraction task.

    The output *format* depends on what the prompt asks for, which is what lets a prompt fix be verified
    without a live model: amounts are numbers only if the prompt says so, dates are ISO only if the prompt
    says so, and bare JSON is returned only if the prompt demands JSON only.
    """
    doc = payload.get("document", "") if isinstance(payload, dict) else str(payload)
    doc = doc if isinstance(doc, str) else json.dumps(doc)
    p = prompt.lower()
    amount_numeric = bool(re.search(r"amount[^\n]*\b(number|numeric|float|decimal)\b", p))
    date_iso = "yyyy-mm-dd" in p or "iso 8601" in p
    json_only = "json" in p  # a mock model that honours any JSON instruction with bare JSON

    def first(rx: re.Pattern) -> str | None:
        m = rx.search(doc)
        return m.group(1) if m else None

    total_raw = first(_TOTAL)
    amount: Any = total_raw
    currency = None
    if total_raw:
        currency = _CURRENCY.get(total_raw.strip()[0])
        if amount_numeric:
            digits = re.sub(r"[^\d.]", "", total_raw.replace(",", ""))
            try:
                amount = float(digits)
            except ValueError:
                amount = None
    date = first(_DATE)
    if date and date_iso:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", date.strip())
        if m:
            date = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    data = {"invoice_number": first(_INV), "vendor": first(_VENDOR), "date": date, "amount": amount,
            "currency": currency}
    body = json.dumps(data, indent=2)
    return body if json_only else f"Here is the extracted invoice data:\n{body}\nLet me know if you need anything else!"


# ---------------------------------------------------------------- JSON parsing
def parse_json_text(raw: str) -> Any:
    text = raw.strip()
    if not text:
        raise NodeError("empty_response", "LLM returned an empty response", details={"raw_output": raw})
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise NodeError("malformed_json", f"LLM output is not valid JSON ({e.msg} at char {e.pos})",
                        details={"raw_output": raw[:1500], "position": e.pos})


# ---------------------------------------------------------------- live calls
def call_model(model: str, prompt: str, payload: Any, system: str | None = None, timeout_s: float = 60.0) -> dict:
    """Dispatch to the configured live provider. Raises NodeError on any provider failure."""
    p = provider()
    if p == "anthropic":
        return call_claude(model, prompt, payload, system, timeout_s)
    if p == "openai":
        return call_openai(model, prompt, payload, system, timeout_s)
    if p == "openrouter":
        return call_openrouter(model, prompt, payload, system, timeout_s)
    raise NodeError("config_error", "Live mode requested but no API key is configured on the server")


def call_openai(model: str, prompt: str, payload: Any, system: str | None = None,
                timeout_s: float = 60.0) -> dict:
    """OpenAI chat completions using the smallest model and minimal token consumption."""
    import httpx

    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise NodeError("config_error", "OpenAI API key is missing (set OPENAI_API_KEY in backend/.env)")

    oa_model = resolve_openai_model(model)

    # Token optimization: compact payload serialization avoids multi-line whitespace tokens
    if isinstance(payload, (dict, list)):
        payload_str = json.dumps(payload, separators=(',', ':'))
    else:
        payload_str = str(payload)

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    else:
        messages.append({
            "role": "system",
            "content": "You are a concise data extractor. Return only the requested output without preamble, markdown commentary, or conversational filler."
        })
    messages.append({"role": "user", "content": f"{prompt.strip()}\n\n<input>\n{payload_str}\n</input>"})

    headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    if os.environ.get("OPENAI_ORG_ID"):
        headers["OpenAI-Organization"] = os.environ["OPENAI_ORG_ID"]
    if os.environ.get("OPENAI_PROJECT_ID"):
        headers["OpenAI-Project"] = os.environ["OPENAI_PROJECT_ID"]

    # Strict token cap to ensure very low token consumption
    max_tokens = int(os.environ.get("OPENAI_MAX_TOKENS", "600"))

    req_body: dict[str, Any] = {
        "model": oa_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }

    # Enable JSON object response format when JSON is requested
    is_json = "json" in prompt.lower() or (system and "json" in system.lower())
    if is_json:
        req_body["response_format"] = {"type": "json_object"}

    target_url = OPENAI_URL
    if target_url.rstrip("/").endswith("/v1"):
        target_url = target_url.rstrip("/") + "/chat/completions"

    try:
        r = httpx.post(target_url, headers=headers, json=req_body, timeout=timeout_s)
    except httpx.TimeoutException:
        raise NodeError("timeout", f"OpenAI request timed out after {timeout_s:.0f}s")
    except httpx.HTTPError as e:
        raise NodeError("api_error", f"Could not reach OpenAI: {type(e).__name__}")
    if r.status_code == 429:
        raise NodeError("rate_limited", "OpenAI rate limit hit (429)")
    if r.status_code == 401:
        raise NodeError("auth_error", "OpenAI authentication failed: invalid API key (401)")
    if r.status_code >= 400:
        detail = ""
        try:
            detail = str(r.json().get("error", {}))[:300]
        except ValueError:
            detail = r.text[:300]
        raise NodeError("api_error", f"OpenAI error {r.status_code}", details={"status_code": r.status_code,
                                                                               "body": detail})
    try:
        body = r.json()
    except ValueError:
        raise NodeError("api_error", "OpenAI returned a non-JSON response")
    if body.get("error"):
        raise NodeError("api_error", f"OpenAI: {str(body['error'])[:300]}")
    choices = body.get("choices") or []
    if not choices:
        raise NodeError("empty_response", "OpenAI returned no choices")
    message = choices[0].get("message") or {}
    text = message.get("content") or ""
    usage = body.get("usage") or {}
    return {
        "text": text if isinstance(text, str) else json.dumps(text),
        "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)},
        "model": body.get("model", oa_model),
        "request_id": body.get("id"),
        "stop_reason": choices[0].get("finish_reason"),
    }


def call_openrouter(model: str, prompt: str, payload: Any, system: str | None = None,
                    timeout_s: float = 60.0) -> dict:
    """OpenRouter (OpenAI-compatible chat completions). Key stays server-side."""
    import httpx

    key = os.environ.get("OPENROUTER_API_KEY", "")
    or_model = OPENROUTER_MODELS.get(model, model)
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": f"{prompt}\n\n<input>\n{json.dumps(payload, indent=2)}\n</input>"})
    headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    if os.environ.get("OPENROUTER_APP_URL"):
        headers["HTTP-Referer"] = os.environ["OPENROUTER_APP_URL"]
    if os.environ.get("OPENROUTER_APP_NAME"):
        headers["X-Title"] = os.environ["OPENROUTER_APP_NAME"]
    try:
        r = httpx.post(OPENROUTER_URL, headers=headers, json={
            "model": or_model, "messages": messages, "max_tokens": 4096,
        }, timeout=timeout_s)
    except httpx.TimeoutException:
        raise NodeError("timeout", f"OpenRouter request timed out after {timeout_s:.0f}s")
    except httpx.HTTPError as e:
        raise NodeError("api_error", f"Could not reach OpenRouter: {type(e).__name__}")
    if r.status_code == 429:
        raise NodeError("rate_limited", "OpenRouter rate limit hit (429)")
    if r.status_code >= 400:
        detail = ""
        try:
            detail = str(r.json().get("error", {}))[:300]
        except ValueError:
            detail = r.text[:300]
        raise NodeError("api_error", f"OpenRouter error {r.status_code}", details={"status_code": r.status_code,
                                                                                   "body": detail})
    try:
        body = r.json()
    except ValueError:
        raise NodeError("api_error", "OpenRouter returned a non-JSON response")
    if body.get("error"):
        raise NodeError("api_error", f"OpenRouter: {str(body['error'])[:300]}")
    choices = body.get("choices") or []
    if not choices:
        raise NodeError("empty_response", "OpenRouter returned no choices")
    message = choices[0].get("message") or {}
    text = message.get("content") or ""
    usage = body.get("usage") or {}
    return {
        "text": text if isinstance(text, str) else json.dumps(text),
        "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)},
        "model": body.get("model", or_model),
        "request_id": body.get("id"),
        "stop_reason": choices[0].get("finish_reason"),
    }


def call_claude(model: str, prompt: str, payload: Any, system: str | None = None, timeout_s: float = 60.0) -> dict:
    import anthropic

    client = anthropic.Anthropic(timeout=timeout_s)
    user = f"{prompt}\n\n<input>\n{json.dumps(payload, indent=2)}\n</input>"
    kwargs: dict[str, Any] = {"model": model, "max_tokens": 4096, "messages": [{"role": "user", "content": user}]}
    if system:
        kwargs["system"] = system
    try:
        resp = client.messages.create(**kwargs)
    except anthropic.APITimeoutError:
        raise NodeError("timeout", f"Claude request timed out after {timeout_s:.0f}s")
    except anthropic.RateLimitError:
        raise NodeError("rate_limited", "Claude API rate limit hit (429)")
    except anthropic.APIStatusError as e:
        raise NodeError("api_error", f"Claude API error {e.status_code}", details={"status_code": e.status_code})
    except anthropic.APIConnectionError:
        raise NodeError("api_error", "Could not reach the Claude API")
    if resp.stop_reason == "refusal":
        raise NodeError("refusal", "Claude declined this request (stop_reason=refusal)")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
    return {"text": text, "usage": usage, "model": resp.model, "request_id": getattr(resp, "_request_id", None),
            "stop_reason": resp.stop_reason}
