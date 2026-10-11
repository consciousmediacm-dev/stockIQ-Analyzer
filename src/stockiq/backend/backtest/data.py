"""
Price loading for backtests.

Sources:
  • yfinance batch download (default) with a per-ticker parquet cache so repeat
    runs don't re-download 10+ years of history.
  • A directory of CSV files (TICKER.csv with Date, Open, High, Low, Close, Volume)
    — useful when the data comes from a paid vendor export.
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".stockiq" / "backtest_prices"
_OHLCV = ["Open", "High", "Low", "Close", "Volume"]
# MA200W needs ~200 weeks of history before the first scorable bar
WARMUP_YEARS = 4.2


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    cols = [c for c in _OHLCV if c in df.columns]
    df = df[cols].dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_prices_csv(directory: str | Path, tickers: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Load TICKER.csv files from a directory."""
    out: dict[str, pd.DataFrame] = {}
    for path in sorted(Path(directory).glob("*.csv")):
        ticker = path.stem.upper()
        if tickers and ticker not in tickers:
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.columns = [c.strip().title() for c in df.columns]
        out[ticker] = _clean(df)
    return out


def load_prices_yf(
    tickers: list[str],
    years: float,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    max_cache_age_hours: float = 20,
    chunk_size: int = 50,
) -> dict[str, pd.DataFrame]:
    """
    Download `years` + warm-up of daily adjusted OHLCV for each ticker.
    Fresh cached parquet files are reused; missing ones are batch-downloaded.
    """
    import yfinance as yf

    start = (datetime.today() - timedelta(days=int((years + WARMUP_YEARS) * 365.25))).strftime("%Y-%m-%d")
    # yfinance treats `end` as exclusive — use tomorrow so today's bar is included
    end = (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    out: dict[str, pd.DataFrame] = {}
    todo: list[str] = []
    for t in tickers:
        path = cache_dir / f"{t}.parquet" if cache_dir else None
        if path and path.exists() and (time.time() - path.stat().st_mtime) < max_cache_age_hours * 3600:
            df = pd.read_parquet(path)
            if not df.empty and df.index.min() <= pd.Timestamp(start) + pd.Timedelta(days=10):
                out[t] = df
                continue
        todo.append(t)

    for i in range(0, len(todo), chunk_size):
        chunk = todo[i:i + chunk_size]
        logger.info("Downloading %d tickers (%d/%d)", len(chunk), i + len(chunk), len(todo))
        try:
            raw = yf.download(
                chunk, start=start, end=end, progress=False,
                auto_adjust=True, group_by="ticker", threads=True,
            )
        except Exception as exc:  # network / rate-limit — skip the chunk, keep going
            logger.warning("Download failed for chunk starting %s: %s", chunk[0], exc)
            continue
        for t in chunk:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = _clean(df.copy())
            except KeyError:
                df = pd.DataFrame()
            if df.empty:
                logger.warning("No data for %s", t)
                continue
            out[t] = df
            if cache_dir:
                cache_dir.mkdir(parents=True, exist_ok=True)
                df.to_parquet(cache_dir / f"{t}.parquet")
    return out
