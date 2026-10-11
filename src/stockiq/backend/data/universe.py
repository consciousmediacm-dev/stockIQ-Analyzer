"""
Ticker universes.

  sp500       — curated S&P list from config/screeners.yml (honours SCREENER_TICKER_COUNT)
  nasdaq100   — config/screeners.yml
  us_equities — every active US-listed common stock / ADR   ┐ from cache/screener/universe.json,
  us_etfs     — every active US-listed ETF                   │ built by
  us_all      — both                                         ┘ cache/scripts/build_universe_cache.py

Symbols use Yahoo-style class separators (BRK-B, not BRK.B).
"""

import io
import json
import logging
import re
from pathlib import Path

import pandas as pd

from stockiq.backend.config import NASDAQ_100_TICKERS, SPX_TICKERS

logger = logging.getLogger(__name__)

UNIVERSE_FILE = Path(__file__).resolve().parents[4] / "cache" / "screener" / "universe.json"
UNIVERSES = ("sp500", "nasdaq100", "us_equities", "us_etfs", "us_all")

# Instruments that aren't ordinary shares — excluded from the equity universe
_NON_COMMON = re.compile(
    r"\b(warrants?|units?|rights?|preferred|pfd|notes? due|debentures?|subordinated|"
    r"trust preferred|depositary shares? representing .*preferred|when issued|contingent value)\b",
    re.IGNORECASE,
)

_EXCHANGES = {
    "A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Q": "NASDAQ",
    "Z": "Cboe BZX", "V": "IEX",
}


def _norm_symbol(sym: str) -> str:
    return sym.strip().upper().replace(".", "-").replace("/", "-")


def _keep(symbol: str, name: str) -> bool:
    if not symbol or "$" in symbol or " " in symbol:
        return False
    return not _NON_COMMON.search(name or "")


def parse_nasdaq_traded(text: str) -> pd.DataFrame:
    """
    Parse nasdaqtrader.com's nasdaqtraded.txt (pipe-delimited, all US-listed securities).
    Returns columns: symbol, name, exchange, is_etf.
    """
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
    df = pd.read_csv(io.StringIO("\n".join(lines)), sep="|", dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    sym_col = "CQS Symbol" if "CQS Symbol" in df.columns else "Symbol"
    df = df[df.get("Test Issue", "N").eq("N")]
    if "Nasdaq Traded" in df.columns:
        df = df[df["Nasdaq Traded"].eq("Y")]
    df["symbol"] = [(c or s) for c, s in zip(df[sym_col], df["Symbol"])]
    df["name"] = df["Security Name"]
    df = df[[_keep(s, n) for s, n in zip(df["symbol"], df["name"])]]
    out = pd.DataFrame({
        "symbol":   df["symbol"].map(_norm_symbol),
        "name":     df["name"].str.strip(),
        "exchange": df["Listing Exchange"].map(lambda x: _EXCHANGES.get(x, x)),
        "is_etf":   df["ETF"].eq("Y"),
    })
    return out.drop_duplicates("symbol").sort_values("symbol").reset_index(drop=True)


def parse_av_listing(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise Alpha Vantage LISTING_STATUS output to the same columns as parse_nasdaq_traded."""
    df = df.fillna("")
    if "status" in df.columns:
        df = df[df["status"].str.lower().eq("active")]
    df = df[[_keep(str(s), str(n)) for s, n in zip(df["symbol"], df["name"])]]
    out = pd.DataFrame({
        "symbol":   df["symbol"].astype(str).map(_norm_symbol),
        "name":     df["name"].astype(str).str.strip(),
        "exchange": df["exchange"].astype(str),
        "is_etf":   df["assetType"].astype(str).str.upper().eq("ETF"),
    })
    return out.drop_duplicates("symbol").sort_values("symbol").reset_index(drop=True)


_cache: list[dict] | None = None


def _load_listing() -> list[dict]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))["securities"]
        except FileNotFoundError:
            logger.warning("%s not found — run cache/scripts/build_universe_cache.py", UNIVERSE_FILE)
            _cache = []
        except Exception as exc:
            logger.warning("Failed to read universe cache: %s", exc)
            _cache = []
    return _cache


def get_universe(name: str = "sp500") -> list[str]:
    """Ticker list for a named universe (see module docstring)."""
    if name == "sp500":
        return list(SPX_TICKERS)
    if name == "nasdaq100":
        return [t for t in NASDAQ_100_TICKERS if isinstance(t, str)]
    listing = _load_listing()
    if name == "us_equities":
        return [s["symbol"] for s in listing if not s["is_etf"]]
    if name == "us_etfs":
        return [s["symbol"] for s in listing if s["is_etf"]]
    if name == "us_all":
        return [s["symbol"] for s in listing]
    raise ValueError(f"Unknown universe {name!r}; choose from {UNIVERSES}")


def get_security_names() -> dict[str, str]:
    """symbol → security name for every listed security (empty if cache not built)."""
    return {s["symbol"]: s["name"] for s in _load_listing()}
