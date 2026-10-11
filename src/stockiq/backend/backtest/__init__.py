"""
Backtesting harness — measures what actually happened after each signal fired.

Modules:
  signals_vec — vectorised signal_score (one value per bar, parity-tested)
  strategies  — per-bar labels for the score and the price-only scanners
  engine      — forward returns (no look-ahead), benchmark excess, summaries
  data        — price loading (yfinance batch download, CSV dir, parquet cache)
  report      — markdown / CSV report writer

Run from the project root:
    python -m stockiq.backend.backtest --tickers 50 --years 10
"""

from stockiq.backend.backtest.engine import (
    DEFAULT_HORIZONS,
    add_forward_returns,
    build_events,
    run_backtest,
    summarize,
)
from stockiq.backend.backtest.signals_vec import score_components, signal_score_series

__all__ = [
    "DEFAULT_HORIZONS",
    "add_forward_returns",
    "build_events",
    "run_backtest",
    "score_components",
    "signal_score_series",
    "summarize",
]
