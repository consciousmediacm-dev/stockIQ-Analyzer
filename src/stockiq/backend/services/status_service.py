"""System status — data-provider health, cache freshness, configured keys, recent problems."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from stockiq.backend.cache import registered_caches
from stockiq.backend.data.providers import provider_status
from stockiq.logging_setup import recent_problems

SCREENER_DIR = Path(__file__).resolve().parents[4] / "cache" / "screener"

# file → (what uses it, max healthy age in days)
CACHE_FILES: dict[str, tuple[str, float]] = {
    "analyst_consensus.json": ("Analyst Buy/Sell Picks", 3),
    "forward_pe.json":        ("Forward P/E Picks, Analyzer valuation card", 3),
    "short_interest.json":    ("Short Squeeze Scanner", 3),
    "fundamentals.json":      ("Munger Value Picks", 10),
    "ticker_metadata.json":   ("Company names & sectors", 10),
    "universe.json":          ("All-US ticker universe", 10),
}

API_KEYS = {
    "ALPHA_VANTAGE_API_KEY": "Alpha Vantage (market data fallback, all-US universe)",
    "GROQ_API_KEY":          "AI Outlook — Groq",
    "GOOGLE_API_KEY":        "AI Outlook — Gemini",
    "DEEPSEEK_API_KEY":      "AI Outlook — DeepSeek",
    "OPENAI_API_KEY":        "AI Outlook — OpenAI",
    "ANTHROPIC_API_KEY":     "AI Outlook — Claude",
}


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 86400


def cache_freshness() -> list[dict]:
    """
    One row per cache file. Age comes from manifest.json (written by the build
    scripts); without it we fall back to file mtime, which on a fresh checkout is
    the clone time — flagged as 'approx'.
    """
    try:
        manifest = json.loads((SCREENER_DIR / "manifest.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        manifest = {}

    rows = []
    for name, (used_by, max_age) in CACHE_FILES.items():
        path = SCREENER_DIR / name
        entry = manifest.get(name, {})
        age, approx = _age_days(entry.get("generated_at")), False
        if age is None and path.exists():
            age = (datetime.now().timestamp() - path.stat().st_mtime) / 86400
            approx = True
        if not path.exists():
            state = "missing"
        elif age is not None and age > max_age:
            state = "stale"
        else:
            state = "ok"
        rows.append({
            "file":     name,
            "used_by":  used_by,
            "state":    state,
            "age_days": None if age is None else round(age, 1),
            "approx":   approx,
            "count":    entry.get("count"),
            "coverage": entry.get("coverage"),
        })
    return rows


def configured_keys() -> list[dict]:
    """Which API keys are present — names only, never values."""
    return [{"key": k, "purpose": v, "set": bool(os.environ.get(k))} for k, v in API_KEYS.items()]


def market_snapshot_status() -> dict:
    """Rows, latest bar and build time of the full-market snapshot this app has loaded."""
    from stockiq.backend.data import market_snapshot as ms
    df = ms.load_market_snapshot()
    return {
        "rows": len(df),
        "latest_bar": None if df.empty else str(df["last_date"].max()),
        "built_at": ms._local_generated_at() or ("bundled with the repo" if ms.REPO_FILE.exists() else None),
    }


def get_system_status() -> dict:
    return {
        "snapshot":  market_snapshot_status(),
        "providers": provider_status(),
        "caches":    cache_freshness(),
        "keys":      configured_keys(),
        "problems":  recent_problems(),
        "registered_caches": len(registered_caches()),
    }
