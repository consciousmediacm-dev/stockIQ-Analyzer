"""
Forecast log + scoring — is the AI outlook any better than a naive guess?

Every freshly generated forecast is appended to $STOCKIQ_DATA_DIR/forecasts.jsonl.
score_forecasts() joins those predictions to actual SPY closes and reports, per
provider and horizon:

  direction hit %   Bullish → close above prior close, Bearish → below,
                    Neutral → within ±0.3%
  always-up hit %   the same metric for a model that always says Bullish
  close error %     |est_close − actual| / actual
  no-change error % the same metric for "SPY closes where it is now"
  in-range %        actual close inside [range_low, range_high]

If the AI can't beat both naive baselines, its forecasts aren't adding value.
Note: on hosts with ephemeral disks (Streamlit Community Cloud) the log resets
on every reboot — point STOCKIQ_DATA_DIR at persistent storage to keep history.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from stockiq.backend.cache import DATA_DIR

logger = logging.getLogger(__name__)

LOG_FILE = DATA_DIR / "forecasts.jsonl"
NEUTRAL_BAND = 0.003
_lock = threading.Lock()


def log_forecast(provider: str, model: str, anchor_price: float | None, days: list[dict],
                 path: Path | None = None) -> None:
    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "anchor_price": anchor_price,
        "days": days,
    }
    path = path or LOG_FILE
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("Could not log forecast: %s", exc)


def load_forecasts(path: Path | None = None) -> list[dict]:
    path = path or LOG_FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _bucket(day_no: int) -> str:
    return "Day 1" if day_no == 1 else ("Days 2–5" if day_no <= 5 else "Days 6–10")


def forecast_rows(records: list[dict], closes: pd.Series) -> pd.DataFrame:
    """One row per (forecast, predicted day) that has an actual close to compare with."""
    closes = closes.dropna().sort_index()
    closes.index = pd.to_datetime(closes.index).normalize()
    prev = closes.shift(1)
    rows = []
    for rec in records:
        anchor = rec.get("anchor_price")
        for n, d in enumerate(rec.get("days", []), start=1):
            dt = pd.Timestamp(d["date"]).normalize()
            if dt not in closes.index or pd.isna(prev.get(dt)):
                continue
            actual, before = float(closes[dt]), float(prev[dt])
            ret = actual / before - 1
            truth = "Neutral" if abs(ret) <= NEUTRAL_BAND else ("Bullish" if ret > 0 else "Bearish")
            rows.append({
                "provider":      rec["provider"],
                "model":         rec.get("model"),
                "generated_at":  rec["generated_at"],
                "horizon":       _bucket(n),
                "date":          dt,
                "direction_hit": d["direction"] == truth,
                "always_up_hit": truth == "Bullish",
                "close_err_pct": abs(d["est_close"] - actual) / actual * 100,
                "naive_err_pct": abs(anchor - actual) / actual * 100 if anchor else None,
                "in_range":      d["range_low"] <= actual <= d["range_high"],
            })
    return pd.DataFrame(rows)


def score_forecasts(records: list[dict], closes: pd.Series) -> pd.DataFrame:
    """Track-record table by provider × horizon (see module docstring)."""
    rows = forecast_rows(records, closes)
    if rows.empty:
        return rows
    g = rows.groupby(["provider", "horizon"])
    table = pd.DataFrame({
        "forecasts":         g["generated_at"].nunique(),
        "days scored":       g.size(),
        "direction hit %":   g["direction_hit"].mean() * 100,
        "always-up hit %":   g["always_up_hit"].mean() * 100,
        "close error %":     g["close_err_pct"].mean(),
        "no-change error %": g["naive_err_pct"].mean(),
        "in-range %":        g["in_range"].mean() * 100,
    }).round(2)
    return table.reset_index()
