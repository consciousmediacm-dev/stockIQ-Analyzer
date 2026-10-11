"""Backtest service — thin wrapper so the frontend never touches data/engine modules directly."""

import pandas as pd

from stockiq.backend.backtest.data import load_prices
from stockiq.backend.backtest.engine import run_backtest
from stockiq.backend.backtest.report import render_markdown
from stockiq.backend.cache import ttl_cache


@ttl_cache(6 * 3600)
def _load(tickers: tuple[str, ...], years: float) -> dict[str, pd.DataFrame]:
    return load_prices(list(tickers), years)


def run_signal_backtest(
    tickers: list[str],
    years: float = 10,
    horizons: tuple[int, ...] = (5, 20, 60),
    step: int = 5,
    benchmark: str = "SPY",
) -> dict:
    """
    Backtest the signal score and price-only scanners over `tickers`.
    Returns run_backtest()'s dict plus "markdown" and "missing" (tickers with no data).
    """
    wanted = tuple(sorted(set(tickers) | {benchmark}))
    prices = _load(wanted, float(years))
    universe = {t: df for t, df in prices.items() if t in tickers}
    start = pd.Timestamp.today().normalize() - pd.DateOffset(days=int(years * 365.25))
    result = run_backtest(universe, prices.get(benchmark), horizons, start=start, step=step)
    result["missing"] = sorted(set(tickers) - set(prices))
    result["markdown"] = render_markdown(result) if result["tables"] else ""
    return result
