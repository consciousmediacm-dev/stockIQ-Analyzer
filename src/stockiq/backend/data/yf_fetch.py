import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def search_companies(query: str) -> list[dict]:
    """Return matching companies from Yahoo Finance search."""
    try:
        quotes = yf.Search(query, max_results=10, news_count=0).quotes
        return [
            {
                "symbol":   r.get("symbol", ""),
                "name":     r.get("shortname") or r.get("longname") or r.get("symbol", ""),
                "exchange": r.get("exchange", ""),
                "type":     r.get("quoteType", ""),
            }
            for r in quotes
            if r.get("symbol") and r.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND", "INDEX")
        ]
    except Exception as exc:
        logger.warning("search_companies failed: %s", exc)
        return []


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
