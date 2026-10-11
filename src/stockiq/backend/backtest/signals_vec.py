"""
Vectorised version of models.signals.signal_score.

signal_score() works on one (row, prev_row) pair, which is fine for the live
card but far too slow to replay over 10 years × 300 tickers. This module
computes the same five components for every bar at once.

Parity with signal_score() is enforced by tests/backend/backtest/test_signals_vec.py
— if you change the scoring rules in one place, change them in both.
"""

import numpy as np
import pandas as pd

from stockiq.backend.config import MA_PERIODS
from stockiq.backend.models.indicators import compute_mas, compute_rsi, compute_weekly_ma200
from stockiq.backend.models.signals import overall_signal

COMPONENTS = ["c_ma_align", "c_cross", "c_momentum", "c_ma200w", "c_rsi"]


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of an OHLCV frame with MA*, MA200W and RSI columns added."""
    out = compute_mas(df.copy())
    out["MA200W"] = compute_weekly_ma200(out)
    out["RSI"] = compute_rsi(out)
    return out


def score_components(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-bar signal components. Expects Close, MA{p} for every p in MA_PERIODS,
    MA200W and RSI (see add_indicators).

    Returns a DataFrame with one column per component plus 'score' and 'label'.
    """
    close = df["Close"]
    n_ma = len(MA_PERIODS)

    # 1. Price vs each MA — NaN MAs count as "not above", exactly like signal_score
    above = sum((close > df[f"MA{p}"]).astype(int) for p in MA_PERIODS)
    below = n_ma - above
    c_align = np.select(
        [above == n_ma, above >= 3, below == n_ma, below >= 3],
        [2, 1, -2, -1],
        default=0,
    )

    # 2. Golden / death cross and MA50-vs-MA200 trend
    ma50, ma200 = df["MA50"], df["MA200"]
    ma50_p, ma200_p = ma50.shift(1), ma200.shift(1)
    have_all = ma50.notna() & ma200.notna() & ma50_p.notna() & ma200_p.notna()
    golden = (ma50_p <= ma200_p) & (ma50 > ma200)
    death = (ma50_p >= ma200_p) & (ma50 < ma200)
    c_cross = np.where(
        ~have_all, 0,
        np.where(golden, 2, np.where(death, -2, np.where(ma50 > ma200, 1, -1))),
    )

    # 3. Short-term momentum: MA5 vs MA20
    ma5, ma20 = df["MA5"], df["MA20"]
    c_mom = np.where(ma5.isna() | ma20.isna(), 0, np.where(ma5 > ma20, 1, -1))

    # 4. Long-term trend: price vs 200-week MA
    ma200w = df["MA200W"]
    c_w = np.where(ma200w.isna(), 0, np.where(close > ma200w, 2, -2))

    # 5. RSI extremes (contrarian)
    rsi = df["RSI"]
    c_rsi = np.where(rsi.isna(), 0, np.where(rsi >= 70, -1, np.where(rsi <= 30, 1, 0)))

    out = pd.DataFrame(
        {
            "c_ma_align": c_align,
            "c_cross":    c_cross,
            "c_momentum": c_mom,
            "c_ma200w":   c_w,
            "c_rsi":      c_rsi,
        },
        index=df.index,
    ).astype(int)
    out["score"] = out[COMPONENTS].sum(axis=1)
    out["label"] = out["score"].map(lambda s: overall_signal(int(s))[0])
    return out


def signal_score_series(df: pd.DataFrame) -> pd.Series:
    """Score only — convenience wrapper around score_components."""
    return score_components(df)["score"]
