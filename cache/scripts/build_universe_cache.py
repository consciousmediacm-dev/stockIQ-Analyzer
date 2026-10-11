"""
Build the all-US-listed ticker universe.

Sources (first that works wins):
  1. nasdaqtrader.com symbol directory — free, no key, every US-listed security
  2. Alpha Vantage LISTING_STATUS      — needs ALPHA_VANTAGE_API_KEY

Filters out test issues, warrants, units, rights, preferreds and notes.
Refuses to overwrite the cache if the new list is implausibly small (< 3,000).

Usage (from project root):
    python cache/scripts/build_universe_cache.py

Writes to: cache/screener/universe.json
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import requests  # noqa: E402

from stockiq.backend.data.universe import UNIVERSE_FILE, parse_av_listing, parse_nasdaq_traded  # noqa: E402

NASDAQ_TRADED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
MIN_EXPECTED = 3000


def from_nasdaq():
    resp = requests.get(NASDAQ_TRADED_URL, timeout=60, headers={"User-Agent": "stockiq-universe/1.0"})
    resp.raise_for_status()
    return parse_nasdaq_traded(resp.text), "nasdaqtrader"


def from_alphavantage():
    from stockiq.backend.data.providers.alphavantage import AlphaVantageProvider
    provider = AlphaVantageProvider()
    if not provider.is_configured():
        raise RuntimeError("ALPHA_VANTAGE_API_KEY not set")
    return parse_av_listing(provider.listing_status()), "alphavantage"


def main() -> int:
    df, source = None, None
    for fn in (from_nasdaq, from_alphavantage):
        try:
            df, source = fn()
            print(f"  {source}: {len(df):,} securities")
            if len(df) >= MIN_EXPECTED:
                break
        except Exception as exc:
            print(f"  {fn.__name__} failed: {exc}")
    if df is None or len(df) < MIN_EXPECTED:
        print(f"Refusing to write: got {0 if df is None else len(df)} securities (< {MIN_EXPECTED}).")
        return 1

    payload = {
        "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {"equities": int((~df["is_etf"]).sum()), "etfs": int(df["is_etf"].sum())},
        "securities": df.to_dict(orient="records"),
    }
    UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    UNIVERSE_FILE.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"Wrote {len(df):,} securities to {UNIVERSE_FILE} ({payload['counts']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
