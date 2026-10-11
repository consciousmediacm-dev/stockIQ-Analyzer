"""
Full-market snapshot: one row of indicators per US-listed stock and ETF.

Built nightly by cache/scripts/build_market_snapshot.py (GitHub Actions) and
published as a Release asset; the app loads it via data/market_snapshot.py and
the Market Screener filters it. Every indicator uses the same functions as the
live pages (moving averages, RSI), so a symbol reads the same
here as in the Stock Analyzer.
"""

import logging
import time
from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd

from stockiq.backend.backtest.signals_vec import add_indicators

logger = logging.getLogger(__name__)

# ~4.4 years: enough for the 200-week MA used by the signal score
HISTORY_DAYS = 1600
MIN_BARS = 30           # below this a symbol is skipped (brand-new listings)
MAX_STALE_DAYS = 7      # last bar older than this (calendar days) → delisted / halted, skipped

SNAPSHOT_COLUMNS = [
    "symbol", "name", "exchange", "is_etf", "last_date", "bars",
    "close", "chg_1d_pct", "ret_1w_pct", "ret_1m_pct", "ret_3m_pct", "ret_1y_pct",
    "volume", "avg_vol_20", "dollar_vol_20", "high_52w", "low_52w", "pct_from_52w_high",
    "ma20", "ma50", "ma200", "ma200w", "dist_ma50_pct", "dist_ma200_pct", "dist_ma200w_pct", "rsi",
    "above_ma_count", "gap_pct",
]


def _ret(close: pd.Series, n: int) -> float | None:
    if len(close) <= n:
        return None
    prev = float(close.iloc[-(n + 1)])
    return round((float(close.iloc[-1]) / prev - 1) * 100, 2) if prev else None


def _num(v, nd: int = 2):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else round(f, nd)


def snapshot_row(symbol: str, ohlcv: pd.DataFrame, meta: dict | None = None,
                 today: date | None = None) -> dict | None:
    """Latest-bar indicators for one symbol, or None if the history is unusable."""
    df = ohlcv.dropna(subset=["Close"]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if len(df) < MIN_BARS:
        return None
    last_date = df.index[-1].date()
    if ((today or date.today()) - last_date).days > MAX_STALE_DAYS:
        return None

    ind = add_indicators(df)
    last = ind.iloc[-1]
    close = df["Close"]
    vol = df["Volume"] if "Volume" in df.columns else pd.Series(0.0, index=df.index)

    year = df.tail(252)
    high_52w, low_52w = float(year["High"].max()), float(year["Low"].min())
    avg_vol_20 = float(vol.tail(20).mean())
    ma200 = _num(last.get("MA200"))
    dist200 = (float(last["Close"]) / ma200 - 1) * 100 if ma200 else None
    ma50 = _num(last.get("MA50"))
    rsi = _num(last.get("RSI"), 1)
    ma200w = _num(last.get("MA200W"))
    mas = [last.get(f"MA{p}") for p in (5, 20, 50, 100, 200)]
    above_ma = sum(1 for m in mas if not pd.isna(m) and float(last["Close"]) > float(m))

    prev_close = float(close.iloc[-2]) if len(close) > 1 else None
    meta = meta or {}
    return {
        "symbol":            symbol,
        "name":              meta.get("name", symbol),
        "exchange":          meta.get("exchange", ""),
        "is_etf":            bool(meta.get("is_etf", False)),
        "last_date":         last_date.isoformat(),
        "bars":              len(df),
        "close":             _num(last["Close"]),
        "chg_1d_pct":        _ret(close, 1),
        "ret_1w_pct":        _ret(close, 5),
        "ret_1m_pct":        _ret(close, 21),
        "ret_3m_pct":        _ret(close, 63),
        "ret_1y_pct":        _ret(close, 252),
        "volume":            _num(vol.iloc[-1], 0),
        "avg_vol_20":        _num(avg_vol_20, 0),
        "dollar_vol_20":     _num(avg_vol_20 * float(close.tail(20).mean()), 0),
        "high_52w":          _num(high_52w),
        "low_52w":           _num(low_52w),
        "pct_from_52w_high": _num((float(last["Close"]) / high_52w - 1) * 100) if high_52w else None,
        "ma20":              _num(last.get("MA20")),
        "ma50":              ma50,
        "ma200":             ma200,
        "ma200w":            ma200w,
        "dist_ma50_pct":     _num((float(last["Close"]) / ma50 - 1) * 100) if ma50 else None,
        "dist_ma200_pct":    _num(dist200),
        "dist_ma200w_pct":   _num((float(last["Close"]) / ma200w - 1) * 100) if ma200w else None,
        "rsi":               rsi,
        "above_ma_count":    above_ma,
        "gap_pct":           _num((float(df["Open"].iloc[-1]) / prev_close - 1) * 100) if prev_close else None,
    }


def build_snapshot(
    symbols: list[str],
    meta: dict[str, dict],
    fetch: Callable[[list[str], date, date], dict[str, pd.DataFrame]],
    chunk_size: int = 200,
    pause: float = 1.0,
    today: date | None = None,
    progress: Callable[[str], None] = print,
) -> pd.DataFrame:
    """
    Fetch history chunk by chunk (keeps memory flat for ~10k symbols) and return
    one snapshot row per usable symbol. `fetch` is providers.get_daily_history
    in production; tests pass a fake.
    """
    today = today or date.today()
    start = today - timedelta(days=HISTORY_DAYS)
    rows: list[dict] = []
    skipped = 0
    t0 = time.time()
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        try:
            data = fetch(chunk, start, today)
        except Exception as exc:  # one bad chunk must not sink the night's run
            logger.warning("chunk %d failed: %s", i // chunk_size, exc)
            data = {}
        for sym in chunk:
            df = data.get(sym)
            row = None
            if df is not None and not df.empty:
                try:
                    row = snapshot_row(sym, df, meta.get(sym), today)
                except Exception as exc:
                    logger.debug("%s skipped: %s", sym, exc)
            if row:
                rows.append(row)
            else:
                skipped += 1
        progress(f"  {min(i + chunk_size, len(symbols)):>6}/{len(symbols)} symbols · "
                 f"{len(rows)} rows · {skipped} skipped · {time.time() - t0:,.0f}s")
        if pause and i + chunk_size < len(symbols):
            time.sleep(pause)
    return pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)
