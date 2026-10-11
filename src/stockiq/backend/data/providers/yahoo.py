"""Yahoo Finance via yfinance — free, no key, unofficial (can be blocked or rate-limited)."""

import logging
from datetime import date, timedelta

import pandas as pd

from stockiq.backend.data.providers.base import OHLCV_COLUMNS, ProviderError

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


class YahooProvider:
    name = "yahoo"
    probe_symbol = "SPY"   # see providers.__init__ circuit breaker

    def __init__(self, chunk_size: int = 100) -> None:
        self.chunk_size = chunk_size

    def is_configured(self) -> bool:
        return True

    def daily_history(self, tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        out: dict[str, pd.DataFrame] = {}
        errors: list[str] = []
        for i in range(0, len(tickers), self.chunk_size):
            chunk = tickers[i:i + self.chunk_size]
            try:
                raw = yf.download(
                    chunk,
                    start=start.isoformat(),
                    # yfinance's `end` is exclusive — +1 day so `end` itself is included
                    end=(end + timedelta(days=1)).isoformat(),
                    progress=False,
                    auto_adjust=True,
                    group_by="ticker",
                    threads=True,
                )
            except Exception as exc:
                errors.append(str(exc))
                continue
            if raw is None or raw.empty:
                continue
            for t in chunk:
                df = _extract(raw, t, single=len(chunk) == 1)
                if df is None:
                    continue
                cols = [c for c in OHLCV_COLUMNS if c in df.columns]
                df = df[cols].dropna(subset=["Close"])
                if not df.empty:
                    out[t] = df
        if not out and errors:
            raise ProviderError(f"yahoo: {errors[0]}")
        return out


def _extract(raw: pd.DataFrame, ticker: str, single: bool = True) -> pd.DataFrame | None:
    """
    Pull one ticker out of a yf.download frame in either column orientation.
    A flat (non-MultiIndex) frame is only trusted when a single ticker was requested.
    """
    if not isinstance(raw.columns, pd.MultiIndex):
        return raw if single else None
    lvl0 = raw.columns.get_level_values(0)
    lvl1 = raw.columns.get_level_values(1)
    if ticker in lvl0:
        return raw[ticker]
    if ticker in lvl1:
        return raw.xs(ticker, level=1, axis=1)
    return None
