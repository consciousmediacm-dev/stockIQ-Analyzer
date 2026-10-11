"""
Sanity checks for OHLCV data before it reaches indicators or the UI.

Bad vendor data is common — zero prices, High < Low, duplicated dates, a
stock that stopped updating weeks ago. validate_ohlcv() repairs what it safely
can, drops what it can't, and reports every issue so callers can log it or
fail over to another provider.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from stockiq.backend.data.providers.base import OHLCV_COLUMNS


@dataclass
class ValidationResult:
    df: pd.DataFrame
    issues: list[str] = field(default_factory=list)
    usable: bool = True


def _last_trading_day(today: date) -> pd.Timestamp:
    ts = pd.Timestamp(today)
    while ts.weekday() >= 5:
        ts -= pd.Timedelta(days=1)
    return ts


def validate_ohlcv(
    df: pd.DataFrame,
    ticker: str = "",
    min_rows: int = 1,
    max_stale_days: int | None = None,
    today: date | None = None,
    split_like_drop: float = 0.55,
    split_like_jump: float = 1.8,
) -> ValidationResult:
    """
    Clean and check a daily OHLCV frame.

    Repairs:  sorts the index, drops duplicate dates (keeps last), drops rows
              with missing/non-positive Close, clamps High/Low to contain Open/Close.
    Flags:    too few rows, stale last bar (> max_stale_days business days old),
              split-like one-day moves (close/prev ≤ 0.55 or ≥ 1.8 — a missed 2:1+
              split or reverse split looks exactly like this). Flag only: genuine
              crashes this size do happen, so the data is kept.
    usable=False when the frame is empty, too short, or stale.
    """
    issues: list[str] = []
    if df is None or df.empty:
        return ValidationResult(pd.DataFrame(columns=OHLCV_COLUMNS), [f"{ticker}: no data"], usable=False)

    out = df.copy()
    out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)

    missing_cols = [c for c in ("Open", "High", "Low", "Close") if c not in out.columns]
    if missing_cols:
        return ValidationResult(out, [f"{ticker}: missing columns {missing_cols}"], usable=False)

    if not out.index.is_monotonic_increasing:
        out = out.sort_index()
    dupes = int(out.index.duplicated(keep="last").sum())
    if dupes:
        issues.append(f"{ticker}: dropped {dupes} duplicate dates")
        out = out[~out.index.duplicated(keep="last")]

    bad_close = out["Close"].isna() | (out["Close"] <= 0)
    if bad_close.any():
        issues.append(f"{ticker}: dropped {int(bad_close.sum())} rows with missing/non-positive close")
        out = out[~bad_close]

    for col in ("Open", "High", "Low"):
        bad = out[col].isna() | (out[col] <= 0)
        if bad.any():
            out.loc[bad, col] = out.loc[bad, "Close"]

    body_hi = out[["Open", "Close"]].max(axis=1)
    body_lo = out[["Open", "Close"]].min(axis=1)
    inverted = (out["High"] < body_hi) | (out["Low"] > body_lo)
    if inverted.any():
        issues.append(f"{ticker}: repaired {int(inverted.sum())} bars where High/Low did not contain Open/Close")
        out["High"] = np.maximum(out["High"], body_hi)
        out["Low"] = np.minimum(out["Low"], body_lo)

    if "Volume" in out.columns:
        out["Volume"] = out["Volume"].fillna(0).clip(lower=0)

    usable = True
    if len(out) < min_rows:
        issues.append(f"{ticker}: only {len(out)} rows (need {min_rows})")
        usable = False

    if len(out) > 1:
        ratio = out["Close"] / out["Close"].shift(1)
        big = ratio[(ratio <= split_like_drop) | (ratio >= split_like_jump)]
        if not big.empty:
            issues.append(
                f"{ticker}: {len(big)} split-like one-day moves "
                f"(first {big.index[0].date()}, ×{big.iloc[0]:.2f}) — possible unadjusted split"
            )

    if max_stale_days is not None and len(out):
        ref = _last_trading_day(today or date.today())
        age = len(pd.bdate_range(out.index[-1], ref)) - 1
        if age > max_stale_days:
            issues.append(f"{ticker}: last bar {out.index[-1].date()} is {age} trading days old")
            usable = False

    return ValidationResult(out, issues, usable)
