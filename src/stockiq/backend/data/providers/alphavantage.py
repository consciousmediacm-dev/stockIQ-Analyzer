"""
Alpha Vantage — official, keyed market data.

Env:
  ALPHA_VANTAGE_API_KEY      required
  ALPHA_VANTAGE_PREMIUM      "true" on a paid plan. Unlocks TIME_SERIES_DAILY_ADJUSTED
                             (split/dividend-adjusted) and a faster request rate.
                             Free keys get TIME_SERIES_DAILY (UNadjusted) — splits
                             will distort moving averages, so the provider marks
                             itself as a last-resort fallback in that mode.
  ALPHA_VANTAGE_RPM          optional requests-per-minute override

Free tier: 25 requests/day, 1 request/second. Premium starts at 75/min.
One request = one ticker's full history, so whole-market scans need premium.
"""

import io
import logging
import os
import threading
import time
from datetime import date

import pandas as pd
import requests

from stockiq.backend.data.providers.base import (
    ProviderError,
    ProviderNotConfigured,
    RateLimitError,
    with_retry,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alphavantage.co/query"


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


class AlphaVantageProvider:
    name = "alphavantage"

    def __init__(
        self,
        api_key: str | None = None,
        premium: bool | None = None,
        requests_per_minute: float | None = None,
        session: requests.Session | None = None,
        timeout: float = 30,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        self.premium = premium if premium is not None else _truthy(os.environ.get("ALPHA_VANTAGE_PREMIUM"))
        rpm = requests_per_minute or float(os.environ.get("ALPHA_VANTAGE_RPM") or (75 if self.premium else 60))
        self._min_interval = 60.0 / rpm
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._session = session or requests.Session()
        self.timeout = timeout

    # ── plumbing ──────────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_call + self._min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _get(self, params: dict) -> requests.Response:
        if not self.api_key:
            raise ProviderNotConfigured("ALPHA_VANTAGE_API_KEY is not set")
        self._throttle()
        try:
            resp = self._session.get(BASE_URL, params={**params, "apikey": self.api_key}, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"alphavantage: {exc}") from exc
        if resp.status_code >= 500:
            raise ProviderError(f"alphavantage: HTTP {resp.status_code}")
        resp.raise_for_status()
        self._raise_for_message(resp)
        return resp

    @staticmethod
    def _raise_for_message(resp: requests.Response) -> None:
        """Alpha Vantage reports errors as HTTP 200 + a JSON message."""
        text = resp.text.lstrip()
        if not text.startswith("{"):
            return
        try:
            payload = resp.json()
        except ValueError:
            return
        msg = payload.get("Note") or payload.get("Information") or payload.get("Error Message")
        if not msg:
            return
        low = msg.lower()
        if "premium" in low or "rate limit" in low or "requests per" in low or "spreading out" in low:
            raise RateLimitError(f"alphavantage: {msg}")
        raise ProviderError(f"alphavantage: {msg}")

    # ── history ───────────────────────────────────────────────────────────────

    def _daily_one(self, ticker: str, outputsize: str) -> pd.DataFrame:
        function = "TIME_SERIES_DAILY_ADJUSTED" if self.premium else "TIME_SERIES_DAILY"
        resp = with_retry(
            lambda: self._get({"function": function, "symbol": ticker.replace("-", "."),
                               "outputsize": outputsize, "datatype": "csv"}),
            attempts=2, retry_on=(ProviderError,), label=f"alphavantage {ticker}",
        )
        return parse_daily_csv(resp.text)

    def daily_history(self, tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        days = (date.today() - start).days
        outputsize = "compact" if days <= 140 else "full"   # compact = last 100 bars
        out: dict[str, pd.DataFrame] = {}
        for t in tickers:
            try:
                df = self._daily_one(t, outputsize)
            except RateLimitError:
                logger.warning("alphavantage quota hit after %d/%d tickers", len(out), len(tickers))
                if not out:
                    raise
                break
            except ProviderError as exc:
                logger.warning("alphavantage %s: %s", t, exc)
                continue
            df = df.loc[pd.Timestamp(start):pd.Timestamp(end)]
            if not df.empty:
                out[t] = df
        return out

    # ── quote & listings ──────────────────────────────────────────────────────

    def quote(self, ticker: str) -> dict:
        """Latest quote in the same shape as data.spy.fetch_spx_quote (minus 52w range)."""
        resp = self._get({"function": "GLOBAL_QUOTE", "symbol": ticker, "datatype": "json"})
        return parse_global_quote(resp.json())

    def listing_status(self, state: str = "active") -> pd.DataFrame:
        """All US stocks/ETFs: symbol, name, exchange, assetType, ipoDate, delistingDate, status."""
        resp = self._get({"function": "LISTING_STATUS", "state": state})
        return pd.read_csv(io.StringIO(resp.text))


# ── parsers (pure — unit-tested) ──────────────────────────────────────────────

def parse_daily_csv(text: str) -> pd.DataFrame:
    """
    Parse TIME_SERIES_DAILY(_ADJUSTED) CSV into an OHLCV frame.
    Adjusted CSV has adjusted_close; OHLC are scaled by adjusted_close/close so the
    result matches yfinance's auto_adjust=True.
    """
    df = pd.read_csv(io.StringIO(text))
    if df.empty or "timestamp" not in df.columns:
        return pd.DataFrame()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df.index.name = None
    if "adjusted_close" in df.columns:
        factor = df["adjusted_close"] / df["close"]
        for c in ("open", "high", "low"):
            df[c] = df[c] * factor
        df["close"] = df["adjusted_close"]
    return df.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
    })[["Open", "High", "Low", "Close", "Volume"]].astype(float)


def parse_global_quote(payload: dict) -> dict:
    q = payload.get("Global Quote") or {}
    price = float(q.get("05. price") or 0)
    if not price:
        return {}
    prev = float(q.get("08. previous close") or 0)
    day = q.get("07. latest trading day") or ""
    try:
        ts = int(pd.Timestamp(day, tz="America/New_York").replace(hour=16).timestamp())
    except Exception:
        ts = 0
    return {
        "price":      price,
        "prev_close": prev,
        "change":     round(float(q.get("09. change") or 0), 2),
        "change_pct": round(float(str(q.get("10. change percent") or "0").rstrip("%")), 4),
        "day_open":   float(q.get("02. open") or 0),
        "day_high":   float(q.get("03. high") or 0),
        "day_low":    float(q.get("04. low") or 0),
        "volume":     int(float(q.get("06. volume") or 0)),
        "w52_high":   None,
        "w52_low":    None,
        "_ts":        ts,
    }
