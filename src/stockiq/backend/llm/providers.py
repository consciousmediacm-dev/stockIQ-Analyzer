"""Multi-provider LLM wrappers, forecast validation/retry, and in-process forecast cache."""

import hashlib
import json
import logging
import os

import requests as _requests

from stockiq.backend.cache import MemoryCache
from stockiq.backend.config import CACHE_TTL
from stockiq.backend.llm.prompts import _SYSTEM, _USER_TMPL, retry_message
from stockiq.backend.llm.track_record import log_forecast
from stockiq.backend.llm.validation import (
    FORECAST_SCHEMA,
    ForecastValidationError,
    parse_forecast,
    validate_forecast,
)

logger = logging.getLogger(__name__)

# Model IDs can be overridden without a code change: STOCKIQ_MODEL_<PROVIDER>=...
PROVIDERS: dict[str, dict] = {
    "groq": {
        "label":   "Llama 3.3 70B (Groq)",
        "model":   "llama-3.3-70b-versatile",
        "env_var": "GROQ_API_KEY",
        "free":    True,
    },
    "deepseek": {
        "label":   "DeepSeek-V3 (DeepSeek)",
        "model":   "deepseek-chat",
        "env_var": "DEEPSEEK_API_KEY",
        "free":    False,
    },
    "gemini": {
        "label":   "Gemini 2.5 Flash (Google)",
        "model":   "gemini-2.5-flash",
        "env_var": "GOOGLE_API_KEY",
        "free":    True,
    },
    "openai": {
        "label":   "GPT-4.1 Mini (OpenAI)",
        "model":   "gpt-4.1-mini",
        "env_var": "OPENAI_API_KEY",
        "free":    False,
    },
    "anthropic": {
        "label":   "Claude Sonnet 5.5 (Anthropic)",
        "model":   "claude-sonnet-5-5",
        "env_var": "ANTHROPIC_API_KEY",
        "free":    False,
    },
}


def get_secret(key: str) -> str:
    return os.environ.get(key, "")


def model_for(provider: str) -> str:
    return os.environ.get(f"STOCKIQ_MODEL_{provider.upper()}") or PROVIDERS[provider]["model"]


# ── Provider calls: (system, user message, api key) → raw text ────────────────

def _complete_anthropic(system: str, user: str, api_key: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    # Sonnet 5.5 for public traffic (half Opus pricing). Structured outputs guarantee
    # schema-valid JSON; server-side fallback ("default" form — the only one Sonnet 5.5
    # accepts) re-runs a refused request on another model inside the same call.
    resp = client.beta.messages.create(
        model=model_for("anthropic"),
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": FORECAST_SCHEMA},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        category = getattr(getattr(resp, "stop_details", None), "category", None)
        raise RuntimeError(f"Claude declined the request (refusal: {category})")
    return next((b.text for b in resp.content if b.type == "text"), "")


def _complete_groq(system: str, user: str, api_key: str) -> str:
    from groq import Groq

    resp = Groq(api_key=api_key).chat.completions.create(
        model=model_for("groq"),
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return resp.choices[0].message.content or ""


def _complete_openai_compatible(url: str, provider: str, system: str, user: str, api_key: str) -> str:
    resp = _requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model":           model_for(provider),
            "max_tokens":      4096,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"] or ""


def _complete_openai(system: str, user: str, api_key: str) -> str:
    return _complete_openai_compatible("https://api.openai.com/v1/chat/completions", "openai", system, user, api_key)


def _complete_deepseek(system: str, user: str, api_key: str) -> str:
    return _complete_openai_compatible("https://api.deepseek.com/chat/completions", "deepseek", system, user, api_key)


def _complete_gemini(system: str, user: str, api_key: str) -> str:
    from google import genai
    from google.genai import types

    resp = genai.Client(api_key=api_key).models.generate_content(
        model=model_for("gemini"),
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=4096,
            response_mime_type="application/json",
        ),
    )
    return resp.text or ""


_CALLERS = {
    "anthropic": _complete_anthropic,
    "openai":    _complete_openai,
    "groq":      _complete_groq,
    "deepseek":  _complete_deepseek,
    "gemini":    _complete_gemini,
}


# ── Generate → parse → validate → (retry once) ────────────────────────────────

def _anchor_price(context_json: str) -> float | None:
    try:
        return float(json.loads(context_json).get("spy_live_price") or 0) or None
    except (ValueError, TypeError, AttributeError):
        return None


def generate_forecast(provider: str, context_json: str, api_key: str) -> list[dict]:
    """
    Call the provider and return 10 validated forecast days. If the first reply
    is malformed (wrong day count, weekend dates, implausible prices…), retry once
    with the specific problems fed back. Raises ForecastValidationError if the
    retry is still invalid.
    """
    caller = _CALLERS[provider]
    anchor = _anchor_price(context_json)
    user = _USER_TMPL.format(context_json=context_json)

    errors: list[str] = []
    for attempt in (1, 2):
        text = caller(_SYSTEM, user, api_key)
        try:
            check = validate_forecast(parse_forecast(text), anchor)
        except ValueError as exc:
            errors = [str(exc)]
        else:
            if check.repairs:
                logger.info("%s forecast repaired: %s", provider, "; ".join(check.repairs))
            if check.ok:
                return check.days
            errors = check.errors
        logger.warning("%s forecast invalid (attempt %d): %s", provider, attempt, "; ".join(errors[:5]))
        user = _USER_TMPL.format(context_json=context_json) + retry_message(errors)
    raise ForecastValidationError(errors)


_forecast_cache = MemoryCache()


def forecast_store_key(cache_key: str, provider: str, user_key: str = "") -> str:
    """
    Cache key for a forecast. Results bought with a visitor's personal API key are
    namespaced by a hash of that key, so they are never served to other visitors
    (and the key itself is never stored).
    """
    key = f"{cache_key}-{provider}"
    if user_key:
        key += "-u" + hashlib.sha256(user_key.encode()).hexdigest()[:12]
    return key


def fetch_ai_prediction(
    cache_key: str,
    _context_json: str,
    provider: str = "groq",
    _user_key: str = "",
) -> list[dict]:
    """Fetch a validated 10-day SPY forecast from the selected AI provider.

    cache_key  = "YYYY-MM-DD-HH-<provider>" — stable for one hour.
    _context_json and _user_key are prefixed with _ to signal they are not
    part of the cache key (personal-key results get their own namespace, see
    forecast_store_key). Returns [] when no API key is available (not cached,
    so adding a key works immediately). Fresh forecasts are logged for scoring.
    """
    if provider not in _CALLERS:
        raise ValueError(f"Unknown provider: {provider!r}")

    store_key = forecast_store_key(cache_key, provider, _user_key)
    result, hit = _forecast_cache.get(store_key)
    if hit:
        return result

    api_key = _user_key or get_secret(PROVIDERS[provider]["env_var"])
    if not api_key:
        return []

    result = generate_forecast(provider, _context_json, api_key)
    _forecast_cache.set(store_key, result, CACHE_TTL["fetch_ai_prediction"])
    log_forecast(provider, model_for(provider), _anchor_price(_context_json), result)
    return result
