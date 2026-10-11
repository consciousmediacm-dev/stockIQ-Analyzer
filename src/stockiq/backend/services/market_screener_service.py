"""Market Screener — filters the nightly full-market snapshot (all US stocks + ETFs)."""

from dataclasses import dataclass, field

import pandas as pd

from stockiq.backend.data.market_snapshot import load_market_snapshot


@dataclass
class ScreenFilters:
    asset_type: str = "all"                 # all | stocks | etfs
    exchanges: list[str] = field(default_factory=list)
    min_price: float = 0.0
    max_price: float = 0.0                  # 0 = no cap
    min_dollar_vol: float = 0.0             # 20-day avg $ volume
    rsi_min: float = 0.0
    rsi_max: float = 100.0
    dist_ma200_min: float | None = None
    dist_ma200_max: float | None = None
    ret_1m_min: float | None = None
    ret_1m_max: float | None = None
    query: str = ""                          # symbol / name contains
    sort_by: str = "dollar_vol_20"
    ascending: bool = False
    top_n: int = 200


PRESETS: dict[str, dict] = {
    "Everything (most liquid first)": {},
    "Above all 5 moving averages": {"_min_above_ma": 5, "sort_by": "ret_3m_pct"},
    "Below all 5 moving averages": {"_max_above_ma": 0, "sort_by": "ret_3m_pct", "ascending": True},
    "Oversold (RSI ≤ 30)":      {"rsi_max": 30, "sort_by": "rsi", "ascending": True},
    "Overbought (RSI ≥ 70)":    {"rsi_min": 70, "sort_by": "rsi"},
    "Near 52-week high (≤ 2%)": {"sort_by": "pct_from_52w_high", "_near_high": 2.0},
    "Biggest movers today":     {"sort_by": "chg_1d_pct", "_abs_sort": True},
}


def get_market_snapshot() -> dict:
    """{"df": snapshot DataFrame, "as_of": latest bar date or None, "rows": int}."""
    df = load_market_snapshot()
    if df.empty:
        return {"df": df, "as_of": None, "rows": 0}
    return {"df": df, "as_of": str(df["last_date"].max()), "rows": len(df)}


def screen_market(df: pd.DataFrame, f: ScreenFilters, near_high: float | None = None,
                  abs_sort: bool = False, min_above_ma: int | None = None,
                  max_above_ma: int | None = None) -> pd.DataFrame:
    """Apply filters and sorting. Pure function — unit-tested without data files."""
    if df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if f.asset_type == "stocks":
        m &= ~df["is_etf"]
    elif f.asset_type == "etfs":
        m &= df["is_etf"]
    if f.exchanges:
        m &= df["exchange"].isin(f.exchanges)
    if f.min_price:
        m &= df["close"] >= f.min_price
    if f.max_price:
        m &= df["close"] <= f.max_price
    if f.min_dollar_vol:
        m &= df["dollar_vol_20"].fillna(0) >= f.min_dollar_vol
    if f.rsi_min > 0:
        m &= df["rsi"] >= f.rsi_min
    if f.rsi_max < 100:
        m &= df["rsi"] <= f.rsi_max
    if f.ret_1m_min is not None:
        m &= df["ret_1m_pct"] >= f.ret_1m_min
    if f.ret_1m_max is not None:
        m &= df["ret_1m_pct"] <= f.ret_1m_max
    if f.dist_ma200_min is not None:
        m &= df["dist_ma200_pct"] >= f.dist_ma200_min
    if f.dist_ma200_max is not None:
        m &= df["dist_ma200_pct"] <= f.dist_ma200_max
    if min_above_ma is not None:
        m &= df["above_ma_count"] >= min_above_ma
    if max_above_ma is not None:
        m &= df["above_ma_count"] <= max_above_ma
    if near_high is not None:
        m &= df["pct_from_52w_high"] >= -near_high
    if f.query:
        q = f.query.strip().upper()
        m &= df["symbol"].str.upper().str.contains(q, regex=False) | df["name"].str.upper().str.contains(q, regex=False)

    out = df[m]
    if f.sort_by in out.columns:
        key = (lambda s: s.abs()) if abs_sort else None
        out = out.sort_values(f.sort_by, ascending=f.ascending, na_position="last", key=key)
    return out.head(f.top_n).reset_index(drop=True)


def filters_from_preset(name: str, **overrides) -> tuple[ScreenFilters, dict]:
    """Build ScreenFilters for a preset; returns (filters, extra kwargs for screen_market)."""
    preset = dict(PRESETS.get(name, {}))
    extra = {}
    if "_near_high" in preset:
        extra["near_high"] = preset.pop("_near_high")
    for key in ("_min_above_ma", "_max_above_ma"):
        if key in preset:
            extra[key[1:]] = preset.pop(key)
    if preset.pop("_abs_sort", False):
        extra["abs_sort"] = True
    preset.update({k: v for k, v in overrides.items() if v is not None})
    return ScreenFilters(**preset), extra
