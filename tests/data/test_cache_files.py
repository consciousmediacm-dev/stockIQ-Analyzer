"""
Sanity checks on the committed screener cache files.

Runs in CI and in the nightly refresh workflow before anything is committed, so
a malformed or near-empty file can never reach main.
"""

import json
from pathlib import Path

import pytest

SCREENER = Path(__file__).resolve().parents[2] / "cache" / "screener"
MIN_TICKERS = 250   # universe is 300; allow for a handful of delistings / gaps

EXPECTED_FIELDS = {
    "analyst_consensus.json": {"recommendationMean", "numberOfAnalystOpinions", "targetMeanPrice"},
    "forward_pe.json":        {"forwardPE"},
    "short_interest.json":    {"shortPercentOfFloat", "shortRatio", "sharesShort"},
    "fundamentals.json":      {"returnOnEquity", "profitMargins"},
    "ticker_metadata.json":   {"name", "sector"},
}


@pytest.mark.parametrize("name, fields", sorted(EXPECTED_FIELDS.items()))
def test_cache_file_is_well_formed(name, fields):
    path = SCREENER / name
    if not path.exists():
        pytest.skip(f"{name} not built yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{name} must be a ticker-keyed object"
    assert len(data) >= MIN_TICKERS, f"{name} has only {len(data)} tickers"
    rows = [v for v in data.values() if isinstance(v, dict)]
    assert len(rows) == len(data), f"{name} has non-object entries"
    with_fields = sum(1 for v in rows if fields & set(v))
    assert with_fields / len(rows) >= 0.8, f"{name}: only {with_fields}/{len(rows)} entries carry {sorted(fields)}"


def test_universe_file_if_present():
    path = SCREENER / "universe.json"
    if not path.exists():
        pytest.skip("universe.json not built yet")
    payload = json.loads(path.read_text(encoding="utf-8"))
    secs = payload["securities"]
    assert len(secs) >= 3000
    assert {"symbol", "name", "exchange", "is_etf"} <= set(secs[0])
    assert len({s["symbol"] for s in secs}) == len(secs)


def test_manifest_if_present():
    path = SCREENER / "manifest.json"
    if not path.exists():
        pytest.skip("manifest.json not written yet")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest.values():
        assert "generated_at" in entry
