"""Full-market snapshot: builder, loader, screener filters, build-script gate — network-free."""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import stockiq.backend.data.market_snapshot as loader
from stockiq.backend.backtest.signals_vec import add_indicators
from stockiq.backend.market.snapshot import SNAPSHOT_COLUMNS, build_snapshot, snapshot_row
from stockiq.backend.services.market_screener_service import (
    PRESETS,
    ScreenFilters,
    filters_from_preset,
    screen_market,
)
from tests.conftest import _make_ohlcv

TODAY = date(2026, 10, 12)


def _hist(n=1200, seed=1, end="2026-10-09", price=100.0):
    df = _make_ohlcv(n=n, base_price=price, seed=seed)
    df.index = pd.bdate_range(end=end, periods=n)
    return df


# ── snapshot_row ──────────────────────────────────────────────────────────────

def test_row_matches_analyzer_indicators_and_has_all_columns():
    df = _hist()
    row = snapshot_row("AAA", df, {"name": "A", "exchange": "NYSE", "is_etf": False}, today=TODAY)
    assert set(row) == set(SNAPSHOT_COLUMNS)
    ind = add_indicators(df).iloc[-1]
    assert row["rsi"] == round(ind["RSI"], 1) and row["ma200"] == round(ind["MA200"], 2)
    expected_above = sum(ind["Close"] > ind[f"MA{p}"] for p in (5, 20, 50, 100, 200))
    assert row["above_ma_count"] == expected_above
    assert row["close"] == round(df["Close"].iloc[-1], 2)
    assert row["ret_1w_pct"] == pytest.approx((df["Close"].iloc[-1] / df["Close"].iloc[-6] - 1) * 100, abs=0.01)
    assert "score" not in row and "bounce_score" not in row     # retired by user decision


def test_young_listing_gets_row_without_long_averages():
    row = snapshot_row("NEW", _hist(n=120), today=TODAY)
    assert row is not None and row["ma200"] is None and row["ma200w"] is None and row["rsi"] is not None


@pytest.mark.parametrize("n, end", [(10, "2026-10-09"), (300, "2026-08-01")])
def test_too_short_or_stale_is_skipped(n, end):
    assert snapshot_row("X", _hist(n=n, end=end), today=TODAY) is None


# ── build_snapshot ────────────────────────────────────────────────────────────

def test_build_snapshot_chunks_and_survives_failures():
    data = {f"T{i}": _hist(seed=i) for i in range(5)}
    calls = []

    def fetch(chunk, start, end):
        calls.append(list(chunk))
        if "T2" in chunk:
            raise ConnectionError("rate limited")
        return {k: data[k] for k in chunk if k in data}

    snap = build_snapshot(list(data) + ["GONE"], {}, fetch, chunk_size=2, pause=0, today=TODAY,
                          progress=lambda m: None)
    assert len(calls) == 3
    assert set(snap["symbol"]) == {"T0", "T1", "T4"}      # T2/T3 chunk failed, GONE has no data
    assert list(snap.columns) == SNAPSHOT_COLUMNS


# ── loader ────────────────────────────────────────────────────────────────────

@pytest.fixture
def snap_df():
    rows = [snapshot_row(f"S{i}", _hist(seed=i, price=20 + 30 * i), {"name": f"Co {i}", "exchange": "NYSE",
                                                                   "is_etf": i % 2 == 1}, today=TODAY)
            for i in range(6)]
    return pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)


def test_loader_prefers_repo_file_then_download(tmp_path, monkeypatch, snap_df):
    repo, local = tmp_path / "repo.parquet", tmp_path / "local.parquet"
    monkeypatch.setattr(loader, "REPO_FILE", repo)
    monkeypatch.setattr(loader, "LOCAL_FILE", local)
    monkeypatch.setattr(loader, "LOCAL_META", tmp_path / "local.json")
    monkeypatch.setattr(loader, "MARKET_SNAPSHOT_URL", "https://example.invalid/snap.parquet")
    monkeypatch.setattr(loader, "_remote_generated_at", lambda: None)     # version check unavailable
    downloads = []

    def fake_download(url, dest):
        downloads.append(url)
        snap_df.to_parquet(dest)
        return True

    monkeypatch.setattr(loader, "_download", fake_download)
    loader.load_market_snapshot.clear()
    assert len(loader.load_market_snapshot()) == 6 and len(downloads) == 1
    loader.load_market_snapshot.clear()
    loader.load_market_snapshot()
    assert len(downloads) == 1                             # fresh local copy reused

    snap_df.head(2).to_parquet(repo)
    loader.load_market_snapshot.clear()
    assert len(loader.load_market_snapshot()) == 2         # repo file wins
    loader.load_market_snapshot.clear()


def test_loader_redownloads_when_a_newer_build_is_published(tmp_path, monkeypatch, snap_df):
    monkeypatch.setattr(loader, "REPO_FILE", tmp_path / "none.parquet")
    monkeypatch.setattr(loader, "LOCAL_FILE", tmp_path / "local.parquet")
    monkeypatch.setattr(loader, "LOCAL_META", tmp_path / "local.json")
    monkeypatch.setattr(loader, "MARKET_SNAPSHOT_URL", "https://example.invalid/snap.parquet")
    version = {"v": "2026-10-11T17:00:00+00:00"}
    monkeypatch.setattr(loader, "_remote_generated_at", lambda: version["v"])
    downloads = []

    def fake_download(url, dest):
        downloads.append(version["v"])
        (snap_df.head(2) if len(downloads) == 1 else snap_df).to_parquet(dest)   # first build was small
        return True

    monkeypatch.setattr(loader, "_download", fake_download)
    loader.load_market_snapshot.clear()
    assert len(loader.load_market_snapshot()) == 2
    loader.load_market_snapshot.clear()
    assert len(loader.load_market_snapshot()) == 2 and len(downloads) == 1    # same build → reuse
    version["v"] = "2026-10-11T18:48:00+00:00"
    loader.load_market_snapshot.clear()
    assert len(loader.load_market_snapshot()) == len(snap_df) and len(downloads) == 2
    loader.load_market_snapshot.clear()


def test_loader_empty_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "REPO_FILE", tmp_path / "none.parquet")
    monkeypatch.setattr(loader, "LOCAL_FILE", tmp_path / "none2.parquet")
    monkeypatch.setattr(loader, "_remote_generated_at", lambda: None)
    monkeypatch.setattr(loader, "_download", lambda url, dest: False)
    loader.load_market_snapshot.clear()
    assert loader.load_market_snapshot().empty
    loader.load_market_snapshot.clear()


# ── screener ──────────────────────────────────────────────────────────────────

def test_screen_filters(snap_df):
    assert screen_market(snap_df, ScreenFilters(asset_type="etfs"))["is_etf"].all()
    assert not screen_market(snap_df, ScreenFilters(asset_type="stocks"))["is_etf"].any()
    out = screen_market(snap_df, ScreenFilters(min_price=100))
    assert (out["close"] >= 100).all()
    out = screen_market(snap_df, ScreenFilters(rsi_max=60, sort_by="rsi", ascending=True))
    assert out["rsi"].is_monotonic_increasing and (out["rsi"] <= 60).all()
    assert list(screen_market(snap_df, ScreenFilters(query="co 3"))["symbol"]) == ["S3"]
    assert len(screen_market(snap_df, ScreenFilters(top_n=2))) == 2
    mid = snap_df["ret_1m_pct"].median()
    out = screen_market(snap_df, ScreenFilters(ret_1m_min=mid))
    assert 0 < len(out) < len(snap_df) and (out["ret_1m_pct"] >= mid).all()
    assert (screen_market(snap_df, ScreenFilters(ret_1m_max=mid))["ret_1m_pct"] <= mid).all()
    assert screen_market(pd.DataFrame(), ScreenFilters()).empty


@pytest.mark.parametrize("preset", list(PRESETS))
def test_every_preset_runs(snap_df, preset):
    f, extra = filters_from_preset(preset)
    screen_market(snap_df, f, **extra)


def test_above_ma_presets(snap_df):
    f, extra = filters_from_preset("Above all 5 moving averages")
    out = screen_market(snap_df, f, **extra)
    assert (out["above_ma_count"] == 5).all()
    f, extra = filters_from_preset("Below all 5 moving averages")
    assert (screen_market(snap_df, f, **extra)["above_ma_count"] == 0).all()


def test_loader_aligns_old_schema(tmp_path, monkeypatch, snap_df):
    old = snap_df.drop(columns=["above_ma_count", "dist_ma200w_pct"]).assign(score=1, bounce_score=2.0)
    path = tmp_path / "old.parquet"
    old.to_parquet(path)
    df = loader._read(path)
    assert list(df.columns) == SNAPSHOT_COLUMNS and df["above_ma_count"].isna().all()


def test_preset_overrides():
    f, _ = filters_from_preset("Oversold (RSI ≤ 30)", asset_type="etfs", rsi_max=None)
    assert f.rsi_max == 30 and f.asset_type == "etfs"


# ── build script gate ─────────────────────────────────────────────────────────

def test_build_script_refuses_low_coverage(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cache" / "scripts"))
    import build_market_snapshot as script

    listing = [{"symbol": f"T{i}", "name": f"T{i}", "exchange": "NYSE", "is_etf": False} for i in range(4)]
    monkeypatch.setattr(script, "_load_listing", lambda: listing)
    data = {"T0": _hist(end=date.today().isoformat())}
    monkeypatch.setattr(script, "get_daily_history",
                        lambda chunk, s, e, use_breaker=True: {k: v for k, v in data.items() if k in chunk})
    out = tmp_path / "snap.parquet"
    assert script.main(["--out", str(out), "--pause", "0"]) == 1 and not out.exists()   # 1/4 = 25%

    data.update({f"T{i}": _hist(seed=i, end=date.today().isoformat()) for i in range(1, 4)})
    assert script.main(["--out", str(out), "--pause", "0"]) == 0
    assert len(pd.read_parquet(out)) == 4 and out.with_suffix(".json").exists()
