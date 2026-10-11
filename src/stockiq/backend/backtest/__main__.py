"""
CLI:  python -m stockiq.backend.backtest [options]

Examples:
  python -m stockiq.backend.backtest --tickers 50 --years 10
  python -m stockiq.backend.backtest --symbols AAPL MSFT NVDA --years 5 --step 20
  python -m stockiq.backend.backtest --csv-dir ~/vendor_export --years 15
"""

import argparse
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from stockiq.backend.backtest.data import WARMUP_YEARS, load_prices_csv, load_prices
from stockiq.backend.backtest.engine import DEFAULT_HORIZONS, run_backtest
from stockiq.backend.backtest.report import write_report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backtest the app's buy/sell signals")
    ap.add_argument("--tickers", type=int, default=50, help="first N tickers of the universe")
    ap.add_argument("--universe", default="sp500",
                    choices=["sp500", "nasdaq100", "us_equities", "us_etfs", "us_all"],
                    help="ticker universe (us_* needs cache/screener/universe.json)")
    ap.add_argument("--sample", type=int, default=0,
                    help="random sample of N tickers from the universe instead of the first N")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--min-dollar-vol", type=float, default=0.0,
                    help="skip samples whose 20-day avg $ volume at the signal date is below this")
    ap.add_argument("--symbols", nargs="*", help="explicit ticker list (overrides --tickers)")
    ap.add_argument("--years", type=float, default=10, help="evaluation window in years")
    ap.add_argument("--horizons", type=int, nargs="*", default=list(DEFAULT_HORIZONS))
    ap.add_argument("--step", type=int, default=5, help="sample every N trading days")
    ap.add_argument("--benchmark", default="SPY")
    ap.add_argument("--csv-dir", help="load TICKER.csv files instead of downloading")
    ap.add_argument("--out", default=f"reports/backtest/{date.today():%Y-%m-%d}")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.symbols:
        tickers = [s.upper() for s in args.symbols]
    else:
        import random

        from stockiq.backend.data.universe import get_universe
        pool = get_universe(args.universe)
        if not pool:
            print(f"Universe {args.universe!r} is empty — build cache/screener/universe.json first.")
            return 1
        tickers = (random.Random(args.seed).sample(pool, min(args.sample, len(pool)))
                   if args.sample else pool[: args.tickers])

    wanted = sorted(set(tickers) | {args.benchmark})
    if args.csv_dir:
        prices = load_prices_csv(args.csv_dir, wanted)
    else:
        prices = load_prices(wanted, args.years)

    bench = prices.get(args.benchmark)
    universe = {t: df for t, df in prices.items() if t in tickers}
    if not universe:
        print("No price data loaded — check network access / ticker symbols.")
        return 1

    start = pd.Timestamp.today().normalize() - pd.DateOffset(days=int(args.years * 365.25))
    result = run_backtest(universe, bench, tuple(args.horizons), start=start, step=args.step,
                          min_dollar_vol=args.min_dollar_vol)
    if result["events"].empty:
        print(f"No scorable bars — need ≥ {WARMUP_YEARS} years of warm-up history before the window.")
        return 1

    path = write_report(result, Path(args.out))
    print(f"Report written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
