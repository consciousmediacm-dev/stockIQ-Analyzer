"""
Backtest engine.

Approach
--------
For every ticker and every trading day t we compute the signals exactly as the
live app would have seen them using data up to and including t's close, then
measure what happened next:

  entry  = Open[t+1]           (you can only act after the signal prints)
  exit   = Close[t+h]          for each horizon h
  ret_h  = exit / entry - 1
  mae_h  = min(Low[t+1..t+h]) / entry - 1   (worst drawdown while holding)
  exc_h  = ret_h - benchmark ret_h on the same dates

Rows are then grouped by signal label and summarised. A "baseline" group (all
bars) is always included — a signal is only useful if it beats the baseline.

Known limitations (also written into every report):
  • Survivorship bias — the universe is today's constituents.
  • Overlapping windows — use step >= max horizon for independent samples.
  • No commissions, slippage, or taxes.
"""

import numpy as np
import pandas as pd

from stockiq.backend.backtest.signals_vec import COMPONENTS, add_indicators, score_components
from stockiq.backend.models.signals import CANDLE_SIGNALS, bounce_score

DEFAULT_HORIZONS: tuple[int, ...] = (5, 20, 60)
SCORE_LABEL_ORDER = ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]


# ── Forward returns ────────────────────────────────────────────────────────────

def add_forward_returns(df: pd.DataFrame, horizons=DEFAULT_HORIZONS) -> pd.DataFrame:
    """Add ret_{h} and mae_{h} columns using next-open entry. No look-ahead in signals."""
    out = df.copy()
    entry = out["Open"].shift(-1)
    low_rev = out["Low"][::-1]
    for h in horizons:
        out[f"ret_{h}"] = out["Close"].shift(-h) / entry - 1
        # min Low over t+1..t+h
        min_low = low_rev.rolling(h, min_periods=h).min()[::-1].shift(-1)
        out[f"mae_{h}"] = min_low / entry - 1
    return out


# ── Scanner replays (price-only scanners) ──────────────────────────────────────

def candle_counts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Green-candle counts as the Candle Screener sees them on each day: the current
    (partial) week/month plus the previous 3 completed ones.
    """
    out = pd.DataFrame(index=df.index)
    for name, freq in (("weekly_green", "W"), ("monthly_green", "M")):
        period = df.index.to_period(freq)
        period_open = df["Open"].groupby(period).transform("first")
        partial_green = (df["Close"] > period_open).astype(int)

        bars = df.groupby(period).agg(Open=("Open", "first"), Close=("Close", "last"))
        green = (bars["Close"] > bars["Open"]).astype(int)
        prev3 = green.shift(1) + green.shift(2) + green.shift(3)
        out[name] = partial_green + prev3.reindex(period).to_numpy()
    return out


def _candle_label(weekly: pd.Series, monthly: pd.Series) -> np.ndarray:
    labels = [lbl for lbl, _ in CANDLE_SIGNALS]
    return np.select(
        [
            (weekly == 4) & (monthly == 4),
            (weekly == 4) & (monthly >= 3),
            (weekly >= 3) & (monthly >= 3),
            weekly >= 2,
        ],
        labels[:4],
        default=labels[4],
    )


def _rsi_zone(rsi: pd.Series) -> np.ndarray:
    return np.select([rsi <= 30, rsi >= 70], ["Oversold (≤30)", "Overbought (≥70)"], default="Neutral")


# ── Panel ──────────────────────────────────────────────────────────────────────

def build_ticker_panel(
    ticker: str,
    ohlcv: pd.DataFrame,
    horizons=DEFAULT_HORIZONS,
    bounce_threshold: float = 5.0,
) -> pd.DataFrame:
    """All signals + forward returns for one ticker, one row per bar."""
    df = ohlcv.dropna(subset=["Open", "High", "Low", "Close"]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if len(df) < 260:
        return pd.DataFrame()

    ind = add_indicators(df)
    comps = score_components(ind)
    fwd = add_forward_returns(df, horizons)
    candles = candle_counts(df)

    dist = (ind["Close"] - ind["MA200"]) / ind["MA200"] * 100
    in_radar = dist.abs() <= bounce_threshold
    b_score = pd.Series(
        [bounce_score(d, r, bounce_threshold) if ok else np.nan
         for d, r, ok in zip(dist, ind["RSI"].fillna(50), in_radar)],
        index=df.index,
    )

    panel = pd.DataFrame(index=df.index)
    panel["ticker"] = ticker
    panel["close"] = df["Close"]
    panel = panel.join(comps)
    panel["rsi"] = ind["RSI"]
    panel["rsi_zone"] = _rsi_zone(ind["RSI"])
    panel["ma200_dist"] = dist
    panel["bounce_radar"] = np.where(
        in_radar, np.where(dist < 0, "In radar · below MA200", "In radar · above MA200"), "Outside radar"
    )
    panel["bounce_score"] = b_score
    panel["weekly_green"] = candles["weekly_green"]
    panel["monthly_green"] = candles["monthly_green"]
    panel["candle_signal"] = _candle_label(candles["weekly_green"], candles["monthly_green"])
    for h in horizons:
        panel[f"ret_{h}"] = fwd[f"ret_{h}"]
        panel[f"mae_{h}"] = fwd[f"mae_{h}"]

    # Warm-up: the live app always has MA200 and MA200W available (it fetches
    # 5y + 1450 days), so only score bars where both exist.
    warm = ind["MA200"].notna() & ind["MA200W"].notna() & candles["monthly_green"].notna()
    return panel[warm]


def build_events(
    prices: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame | None = None,
    horizons=DEFAULT_HORIZONS,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    step: int = 1,
    bounce_threshold: float = 5.0,
) -> pd.DataFrame:
    """
    Long panel (date, ticker, signals…, ret_h, mae_h, exc_h) across the universe.

    step > 1 keeps every step-th bar per ticker to reduce overlap between
    forward windows (step >= max(horizons) gives non-overlapping samples).
    """
    frames = []
    for ticker, df in prices.items():
        p = build_ticker_panel(ticker, df, horizons, bounce_threshold)
        if p.empty:
            continue
        if start is not None:
            p = p[p.index >= pd.Timestamp(start)]
        if end is not None:
            p = p[p.index <= pd.Timestamp(end)]
        frames.append(p)
    if not frames:
        return pd.DataFrame()

    events = pd.concat(frames)
    events.index.name = "date"

    if benchmark is not None and not benchmark.empty:
        bench = add_forward_returns(benchmark.sort_index(), horizons)
        for h in horizons:
            events[f"exc_{h}"] = events[f"ret_{h}"] - bench[f"ret_{h}"].reindex(events.index).to_numpy()
    else:
        for h in horizons:
            events[f"exc_{h}"] = np.nan

    # Cross-sectional: the Bounce Radar shows the top 30 by score each day
    ranks = events.groupby(level="date")["bounce_score"].rank(ascending=False, method="first")
    events["bounce_top30"] = np.where(ranks <= 30, "Top 30 by bounce score", "Not shown")

    # Subsample on a shared date grid so cross-sectional groups stay aligned
    if step > 1:
        grid = events.index.unique().sort_values()[::step]
        events = events[events.index.isin(grid)]
    return events


# ── Summaries ──────────────────────────────────────────────────────────────────

def summarize(events: pd.DataFrame, by: str, horizons=DEFAULT_HORIZONS, order: list | None = None) -> pd.DataFrame:
    """
    Per-group stats for each horizon:
      n, tickers, hit % (ret > 0), mean %, median %, mean excess %, beat bench %,
      avg MAE %, t-stat of mean excess (overlap inflates this when step < horizon).
    A 'ALL (baseline)' row is appended.
    """
    rows = []

    def _stats(g: pd.DataFrame, label: str) -> dict:
        row: dict = {"group": label, "n": len(g), "tickers": g["ticker"].nunique()}
        for h in horizons:
            r = g[f"ret_{h}"].dropna()
            e = g[f"exc_{h}"].dropna()
            m = g[f"mae_{h}"].dropna()
            row[f"hit%_{h}d"] = round((r > 0).mean() * 100, 1) if len(r) else np.nan
            row[f"mean%_{h}d"] = round(r.mean() * 100, 2) if len(r) else np.nan
            row[f"median%_{h}d"] = round(r.median() * 100, 2) if len(r) else np.nan
            row[f"excess%_{h}d"] = round(e.mean() * 100, 2) if len(e) else np.nan
            row[f"beat%_{h}d"] = round((e > 0).mean() * 100, 1) if len(e) else np.nan
            row[f"mae%_{h}d"] = round(m.mean() * 100, 2) if len(m) else np.nan
            sd = e.std()
            row[f"t_{h}d"] = round(e.mean() / sd * np.sqrt(len(e)), 2) if len(e) > 1 and sd > 0 else np.nan
        return row

    groups = events.groupby(by, sort=False)
    keys = list(groups.groups.keys())
    if order:
        keys = [k for k in order if k in groups.groups] + [k for k in keys if k not in order]
    elif all(isinstance(k, (int, float, np.integer, np.floating)) for k in keys):
        keys = sorted(keys, reverse=True)   # numeric: most bullish first
    else:
        keys = sorted(keys, key=str)
    for k in keys:
        rows.append(_stats(groups.get_group(k), str(k)))
    rows.append(_stats(events, "ALL (baseline)"))
    return pd.DataFrame(rows).set_index("group")


def component_regression(events: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """
    OLS of excess return on the five score components (with intercept).
    Coefficients are in % excess return per +1 component point — a data-driven
    hint at which components deserve weight. Diagnostic only; not auto-applied.
    """
    col = f"exc_{horizon}" if events[f"exc_{horizon}"].notna().any() else f"ret_{horizon}"
    data = events[COMPONENTS + [col]].dropna()
    if len(data) < len(COMPONENTS) + 10:
        return pd.DataFrame()
    X = np.column_stack([np.ones(len(data)), data[COMPONENTS].to_numpy(dtype=float)])
    y = data[col].to_numpy(dtype=float) * 100
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(len(y) - X.shape[1], 1)
    sigma2 = resid @ resid / dof
    try:
        se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
    except np.linalg.LinAlgError:
        se = np.full(X.shape[1], np.nan)
    return pd.DataFrame(
        {"coef_%": beta.round(3), "t": (beta / se).round(2)},
        index=["intercept"] + COMPONENTS,
    )


def run_backtest(
    prices: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame | None = None,
    horizons=DEFAULT_HORIZONS,
    start=None,
    end=None,
    step: int = 5,
) -> dict:
    """
    Full backtest. Returns {"events": DataFrame, "tables": {title: DataFrame},
    "regression": {h: DataFrame}, "meta": {...}}.
    """
    events = build_events(prices, benchmark, horizons, start=start, end=end, step=step)
    if events.empty:
        return {"events": events, "tables": {}, "regression": {}, "meta": {"tickers": 0, "rows": 0}}

    tables = {
        "Signal score label (Stock Analyzer card)": summarize(events, "label", horizons, SCORE_LABEL_ORDER),
        "Signal score (raw −8 … +8)": summarize(events, "score", horizons),
    }
    for c in COMPONENTS:
        tables[f"Component · {c}"] = summarize(events, c, horizons)
    tables["RSI zone (NASDAQ RSI Scanner)"] = summarize(events, "rsi_zone", horizons)
    tables["MA200 Bounce Radar (±5%)"] = summarize(events, "bounce_radar", horizons)
    tables["MA200 Bounce Radar · top 30 per day"] = summarize(events, "bounce_top30", horizons)
    tables["Candle Screener signal"] = summarize(
        events, "candle_signal", horizons, [lbl for lbl, _ in CANDLE_SIGNALS]
    )

    regression = {h: component_regression(events, h) for h in horizons}
    meta = {
        "tickers": int(events["ticker"].nunique()),
        "rows": int(len(events)),
        "start": str(events.index.min().date()),
        "end": str(events.index.max().date()),
        "horizons": list(horizons),
        "step": step,
        "benchmark": benchmark is not None and not benchmark.empty,
    }
    return {"events": events, "tables": tables, "regression": regression, "meta": meta}
