"""Tests for the backtesting harness — all network-free."""

import numpy as np
import pandas as pd
import pytest

from stockiq.backend.backtest.engine import (
    add_forward_returns,
    build_events,
    candle_counts,
    component_regression,
    run_backtest,
    summarize,
)
from stockiq.backend.backtest.report import render_markdown, write_report
from stockiq.backend.backtest.signals_vec import add_indicators, score_components
from stockiq.backend.models.signals import candle_momentum_signal, signal_score
from tests.conftest import _make_ohlcv


def _long(seed: int, n: int = 1600, base: float = 100.0) -> pd.DataFrame:
    return _make_ohlcv(n=n, base_price=base, seed=seed)


# ── Parity with the live scoring function ─────────────────────────────────────

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_vectorised_score_matches_signal_score(seed):
    df = add_indicators(_long(seed))
    comps = score_components(df)
    for i in range(1, len(df)):
        expected, _ = signal_score(df.iloc[i], df.iloc[i - 1])
        assert comps["score"].iloc[i] == expected, f"mismatch at bar {i} ({df.index[i].date()})"


def test_score_components_cover_full_range_and_labels():
    comps = score_components(add_indicators(_long(4)))
    assert comps["score"].between(-8, 8).all()
    assert set(comps["label"]) <= {"STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"}


# ── Forward returns: next-open entry, no look-ahead ───────────────────────────

def _toy() -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=6)
    return pd.DataFrame(
        {
            "Open":  [10, 11, 12, 13, 14, 15],
            "High":  [10, 11, 12, 13, 14, 15],
            "Low":   [9, 8, 11, 7, 13, 14],
            "Close": [10, 11, 12, 13, 14, 15],
        },
        index=idx,
        dtype=float,
    )


def test_forward_return_uses_next_open_and_future_close():
    out = add_forward_returns(_toy(), horizons=(2,))
    # signal on bar 0 → enter Open[1]=11, exit Close[2]=12
    assert out["ret_2"].iloc[0] == pytest.approx(12 / 11 - 1)
    # last 2 bars have no complete forward window
    assert out["ret_2"].iloc[-2:].isna().all()


def test_mae_is_min_low_over_holding_window():
    out = add_forward_returns(_toy(), horizons=(3,))
    # bar 0: hold bars 1..3 → lows 8, 11, 7 → min 7; entry Open[1] = 11
    assert out["mae_3"].iloc[0] == pytest.approx(7 / 11 - 1)
    # bar 1: hold bars 2..4 → lows 11, 7, 13 → min 7; entry Open[2] = 12
    assert out["mae_3"].iloc[1] == pytest.approx(7 / 12 - 1)


def test_signals_do_not_change_when_future_bars_are_removed():
    """A signal on day t must depend only on data ≤ t."""
    full = _long(5)
    cut = full.iloc[:1400]
    a = score_components(add_indicators(full)).iloc[:1400]
    b = score_components(add_indicators(cut))
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(candle_counts(full).iloc[:1400], candle_counts(cut))


# ── Candle counts replay the live screener ────────────────────────────────────

@pytest.mark.parametrize("cut", [700, 903, 1250])
def test_candle_counts_match_live_screener_logic(cut):
    df = _long(6).iloc[:cut]
    # live screener logic (spx_candle.py)
    weekly = df[["Open", "Close"]].resample("W").agg({"Open": "first", "Close": "last"}).tail(4)
    monthly = df[["Open", "Close"]].resample("ME").agg({"Open": "first", "Close": "last"}).tail(4)
    wg = int((weekly["Close"] > weekly["Open"]).sum())
    mg = int((monthly["Close"] > monthly["Open"]).sum())

    counts = candle_counts(df).iloc[-1]
    assert int(counts["weekly_green"]) == wg
    assert int(counts["monthly_green"]) == mg


def test_candle_momentum_signal_tiers():
    assert candle_momentum_signal(4, 4)[1] == 1
    assert candle_momentum_signal(4, 3)[1] == 2
    assert candle_momentum_signal(3, 3)[1] == 3
    assert candle_momentum_signal(2, 0)[1] == 4
    assert candle_momentum_signal(1, 4)[1] == 5


# ── Events / summaries ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def universe():
    prices = {f"T{i}": _long(10 + i, base=50 + 10 * i) for i in range(4)}
    bench = _long(99, base=300)
    return prices, bench


def test_build_events_adds_excess_and_respects_step(universe):
    prices, bench = universe
    ev1 = build_events(prices, bench, horizons=(5,), step=1)
    ev5 = build_events(prices, bench, horizons=(5,), step=5)
    assert {"exc_5", "ret_5", "mae_5", "score", "candle_signal", "bounce_top30"} <= set(ev1.columns)
    assert len(ev5) < len(ev1) / 4
    # same dates for every ticker after grid subsampling
    per_date = ev5.groupby(level="date")["ticker"].nunique()
    assert (per_date == per_date.max()).mean() > 0.95

    row = ev1.dropna(subset=["exc_5"]).iloc[0]
    bench_fwd = add_forward_returns(bench, (5,))
    assert row["exc_5"] == pytest.approx(row["ret_5"] - bench_fwd.loc[row.name, "ret_5"])


def test_summarize_has_baseline_and_counts(universe):
    prices, bench = universe
    ev = build_events(prices, bench, horizons=(20,), step=5)
    tbl = summarize(ev, "label", (20,))
    assert "ALL (baseline)" in tbl.index
    assert tbl.loc["ALL (baseline)", "n"] == len(ev)
    assert tbl.drop("ALL (baseline)")["n"].sum() == len(ev)


def test_component_regression_recovers_planted_effect(universe):
    prices, bench = universe
    ev = build_events(prices, bench, horizons=(20,), step=1).copy()
    rng = np.random.default_rng(0)
    # plant: each +1 of c_momentum adds exactly 1% excess return
    ev["exc_20"] = ev["c_momentum"] * 0.01 + rng.normal(0, 0.001, len(ev))
    reg = component_regression(ev, 20)
    assert reg.loc["c_momentum", "coef_%"] == pytest.approx(1.0, abs=0.05)
    assert abs(reg.loc["c_rsi", "coef_%"]) < 0.05


def test_run_backtest_and_report(universe, tmp_path):
    prices, bench = universe
    result = run_backtest(prices, bench, horizons=(5, 20), step=5)
    assert result["meta"]["tickers"] == 4
    assert "Signal score label (Stock Analyzer card)" in result["tables"]
    md = render_markdown(result)
    assert "Survivorship bias" in md and "ALL (baseline)" in md
    path = write_report(result, tmp_path)
    assert path.exists()
    assert any(p.suffix == ".csv" for p in tmp_path.iterdir())


def test_run_backtest_empty_when_history_too_short():
    result = run_backtest({"X": _make_ohlcv(200)}, None, horizons=(5,))
    assert result["events"].empty and result["tables"] == {}


# ── grid sampling & point-in-time liquidity filter ────────────────────────────

def test_benchmark_grid_matches_global_grid(universe):
    """Per-ticker grid filtering (memory-flat path) gives the same samples as the global grid."""
    prices, bench = universe
    with_bench = build_events(prices, bench, horizons=(5,), step=10)
    no_bench = build_events(prices, None, horizons=(5,), step=10)
    assert len(with_bench) > 0
    per_date = with_bench.groupby(level="date")["ticker"].nunique()
    assert (per_date == len(prices)).mean() > 0.95          # same dates for every ticker
    assert abs(len(with_bench) - len(no_bench)) <= len(prices) * 2


def test_min_dollar_vol_filters_at_signal_date(universe):
    prices, bench = universe
    full = build_events(prices, bench, horizons=(5,), step=5)
    cut = full["dollar_vol_20"].median()
    liquid = build_events(prices, bench, horizons=(5,), step=5, min_dollar_vol=cut)
    assert 0 < len(liquid) < len(full)
    assert (liquid["dollar_vol_20"] >= cut).all()


def test_cli_universe_sample(monkeypatch, tmp_path):
    import stockiq.backend.backtest.__main__ as cli
    import stockiq.backend.data.universe as uni

    monkeypatch.setattr(uni, "_cache", [{"symbol": f"T{i}", "name": "", "exchange": "", "is_etf": False}
                                        for i in range(10)])
    seen = {}

    def fake_load(tickers, years):
        seen["tickers"] = tickers
        return {}

    monkeypatch.setattr(cli, "load_prices", fake_load)
    assert cli.main(["--universe", "us_equities", "--sample", "4", "--out", str(tmp_path)]) == 1  # no data
    assert len(set(seen["tickers"]) - {"SPY"}) == 4


# ── Buying Pressure (BX) replay matches the live panel ────────────────────────

@pytest.mark.parametrize("timeframe", ["monthly", "weekly"])
def test_bx_replay_matches_live_panel(timeframe):
    from stockiq.backend.backtest.engine import buying_pressure_strength
    from stockiq.backend.models.indicators import compute_buying_pressure

    df = _long(21, n=1600)          # ends 2024-12-31, so every bar here is in the past
    replay = buying_pressure_strength(df, timeframe)
    per = "M" if timeframe == "monthly" else "W-FRI"
    periods = df.index.to_period(per)
    ends = [d for d, nxt in zip(df.index[:-1], periods[1:]) if d.to_period(per) != nxt]   # last day of each period

    checked = 0
    for end in ends[-40:]:
        nxt_day = df.index[df.index.get_loc(end) + 1]
        live = compute_buying_pressure(df.loc[:end], timeframe)
        expected = replay.loc[nxt_day]
        if np.isnan(expected):
            assert live["strength"] == 0 and not live["signal"]
            continue
        assert live["strength"] == int(expected), f"{timeframe} bar ending {end.date()}"
        checked += 1
    assert checked >= 20


def test_bx_columns_in_events(universe):
    prices, bench = universe
    ev = build_events(prices, bench, horizons=(20,), step=20)
    assert set(ev["bx_weekly"]) <= {"3/3 · strong signal", "2/3 · signal", "0–1 · no signal", "n/a"}
    result = run_backtest(prices, bench, horizons=(20,), step=20)
    assert "Buying Pressure (BX) · monthly" in result["tables"]
