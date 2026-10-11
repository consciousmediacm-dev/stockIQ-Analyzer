import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

logging.getLogger("yfinance").setLevel(logging.CRITICAL)


# Every Yahoo quote type that has daily price history the analyzer can chart
SEARCHABLE_TYPES = ("EQUITY", "ETF", "MUTUALFUND", "INDEX", "CRYPTOCURRENCY", "CURRENCY", "FUTURE")


def search_companies(query: str) -> list[dict]:
    """
    Find symbols by company name or ticker.
    Merges Yahoo Finance search (global stocks, ETFs, funds, indices, crypto, FX,
    futures) with the local all-US listing (works offline). An exact symbol match
    is always listed first; duplicates are removed.
    """
    from stockiq.backend.data.universe import search_universe

    local = search_universe(query, limit=15)
    remote: list[dict] = []
    try:
        quotes = yf.Search(query, max_results=20, news_count=0).quotes
        remote = [
            {
                "symbol":   r.get("symbol", ""),
                "name":     r.get("shortname") or r.get("longname") or r.get("symbol", ""),
                "exchange": r.get("exchange", ""),
                "type":     r.get("quoteType", ""),
            }
            for r in quotes
            if r.get("symbol") and r.get("quoteType") in SEARCHABLE_TYPES
        ]
    except Exception as exc:
        logger.warning("search_companies failed: %s", exc)

    exact = [r for r in local + remote if r["symbol"].upper() == query.strip().upper().replace(".", "-")]
    merged, seen = [], set()
    for r in exact[:1] + remote + local:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            merged.append(r)
    return merged[:25]


def fetch_ohlcv(ticker: str, period_days: int) -> pd.DataFrame:
    """
    Daily adjusted OHLCV history for a single ticker, through today (inclusive).
    Fetches extra history (period_days + 1450) so long-period MAs have enough warmup data.
    Served by the provider chain (Yahoo → Alpha Vantage) with validation; returns an
    empty DataFrame when no provider has data.
    """
    from stockiq.backend.data.providers import get_daily_history

    start = (datetime.today() - timedelta(days=period_days + 1450)).date()
    data = get_daily_history([ticker], start, datetime.today().date())
    # Callers index df["Close"] even when empty — keep the OHLCV columns
    return data.get(ticker, pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"]))


def get_company_name(ticker: str) -> str:
    """Fetch the long company name from yfinance; falls back to ticker on error."""
    try:
        return yf.Ticker(ticker).info.get("longName", ticker)
    except Exception as exc:
        logger.warning("get_company_name failed: %s", exc)
        return ticker
