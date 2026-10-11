"""Write a backtest result to Markdown + CSV."""

from datetime import datetime
from pathlib import Path

import pandas as pd

CAVEATS = """\
**Read before trusting these numbers**

- **Survivorship bias** — the universe is *today's* constituents, so stocks that
  were dropped or went bankrupt are missing. This flatters every long signal.
- **Overlapping windows** — when `step` < horizon, consecutive samples share most
  of their forward window, so t-stats are inflated. Use `--step` ≥ the horizon to check.
- **No costs** — commissions, spread, slippage and taxes are ignored.
- **Entry** is the next day's open after the signal; **exit** is the close h trading days later.
- **Excess** is return minus the benchmark's return over the same dates.
- Fundamentals-based scanners (Squeeze, Analyst Buy/Sell, Munger, Forward P/E) are
  **not** backtested — we only hold today's fundamentals snapshot, and using it on
  past dates would be look-ahead bias. They need point-in-time history first.
"""

HOW_TO_READ = """\
**How to read a table** — compare each row to the `ALL (baseline)` row. A useful
buy signal has higher `excess%` and `beat%` than baseline with |t| ≳ 2; a useful
sell signal has lower. Example: if `STRONG BUY` shows `excess%_20d = 0.05` and the
baseline shows `0.02`, the label adds ~0.03% per 20 days — noise, not edge.
"""


def _fmt_table(df: pd.DataFrame, horizon: int) -> str:
    cols = ["n", "tickers"] + [c for c in df.columns if c.endswith(f"_{horizon}d")]
    return df[cols].to_markdown()


def render_markdown(result: dict, focus_horizon: int | None = None) -> str:
    meta = result["meta"]
    horizons = meta.get("horizons", [])
    h = focus_horizon or (horizons[len(horizons) // 2] if horizons else 20)
    lines = [
        "# StockIQ signal backtest",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} · {meta.get('tickers', 0)} tickers · "
        f"{meta.get('rows', 0):,} samples · {meta.get('start')} → {meta.get('end')} · "
        f"step {meta.get('step')} · benchmark: {'SPY' if meta.get('benchmark') else 'none'}",
        "",
        CAVEATS,
        HOW_TO_READ,
        f"Tables below show the **{h}-day** horizon; the CSVs have every horizon.",
        "",
    ]
    for title, table in result["tables"].items():
        lines += [f"## {title}", "", _fmt_table(table, h), ""]

    reg = result["regression"].get(h)
    if reg is not None and not reg.empty:
        lines += [
            f"## Component regression ({h}-day excess return)",
            "",
            "Coefficient = % excess return per +1 point of that component, all else equal. "
            "Today every component gets a hand-picked weight (±1 or ±2); a component with a "
            "near-zero or negative coefficient here is a candidate to down-weight or flip.",
            "",
            reg.to_markdown(),
            "",
        ]
    return "\n".join(lines)


def write_report(result: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(render_markdown(result), encoding="utf-8")
    for title, table in result["tables"].items():
        slug = "".join(ch if ch.isalnum() else "_" for ch in title.lower()).strip("_")
        while "__" in slug:
            slug = slug.replace("__", "_")
        table.to_csv(out / f"{slug}.csv")
    for h, reg in result["regression"].items():
        if not reg.empty:
            reg.to_csv(out / f"component_regression_{h}d.csv")
    return out / "report.md"
