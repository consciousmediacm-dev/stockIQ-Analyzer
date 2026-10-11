"""
Build the full-market snapshot: indicators for every active US stock and ETF.

Runs nightly in .github/workflows/market_snapshot.yml after the US close and is
published as the `market_snapshot.parquet` asset of the `market-data` release.

Usage (from project root):
    python cache/scripts/build_market_snapshot.py --out dist/market_snapshot.parquet
    python cache/scripts/build_market_snapshot.py --limit 300      # quick local test

Refuses to write (exit 1) when fewer than --min-coverage of the universe produced
a row, so a rate-limited or blocked night never replaces a good snapshot.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from stockiq.backend.data.providers import get_daily_history, with_retry  # noqa: E402
from stockiq.backend.data.providers.base import ProviderError  # noqa: E402
from stockiq.backend.data.universe import _load_listing  # noqa: E402
from stockiq.backend.market.snapshot import build_snapshot  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", default="dist/market_snapshot.parquet")
    ap.add_argument("--limit", type=int, default=0, help="only the first N symbols (testing)")
    ap.add_argument("--chunk", type=int, default=200)
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between chunks (rate limits)")
    ap.add_argument("--min-coverage", type=float, default=0.70)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    listing = _load_listing()
    if not listing:
        print("universe.json missing — run cache/scripts/build_universe_cache.py first")
        return 1
    meta = {s["symbol"]: s for s in listing}
    symbols = sorted(meta)[: args.limit or None]
    print(f"Building snapshot for {len(symbols):,} symbols "
          f"({sum(meta[s]['is_etf'] for s in symbols):,} ETFs)")

    def fetch(chunk, start, end):
        return with_retry(lambda: get_daily_history(chunk, start, end, use_breaker=False),
                          attempts=3, base_delay=5, retry_on=(ProviderError,), label="snapshot chunk")

    snap = build_snapshot(symbols, meta, fetch, chunk_size=args.chunk, pause=args.pause)

    coverage = len(snap) / len(symbols) if symbols else 0
    print(f"Rows: {len(snap):,}/{len(symbols):,} ({coverage:.0%})")
    if coverage < args.min_coverage:
        print(f"REFUSING to publish: coverage below {args.min_coverage:.0%}")
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    snap.to_parquet(out, index=False)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbols": len(symbols),
        "rows": len(snap),
        "coverage": round(coverage, 3),
        "etfs": int(snap["is_etf"].sum()),
        "latest_bar": snap["last_date"].max() if len(snap) else None,
    }
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2))
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB) · {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
