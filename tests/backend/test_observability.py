"""Tests for logging setup, system status and the cache-build safety gate."""

import json
import logging
import sys
from pathlib import Path

import pytest

import stockiq.backend.services.status_service as status_service
from stockiq.logging_setup import RingBufferHandler, configure_logging, recent_problems

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cache" / "scripts"))
import _common  # noqa: E402


def test_ring_buffer_keeps_warnings_only_and_is_bounded():
    h = RingBufferHandler(capacity=3)
    log = logging.getLogger("test.ring")
    log.addHandler(h)
    log.setLevel(logging.DEBUG)
    try:
        log.info("ignored")
        for i in range(5):
            log.warning("w%d", i)
    finally:
        log.removeHandler(h)
    assert [r["message"] for r in h.records] == ["w2", "w3", "w4"]


def test_configure_logging_is_idempotent_and_feeds_status():
    configure_logging()
    configure_logging()
    logging.getLogger("test.status").error("provider exploded")
    assert any(p["message"] == "provider exploded" for p in recent_problems())


def test_cache_freshness_uses_manifest_and_flags_stale(tmp_path, monkeypatch):
    (tmp_path / "analyst_consensus.json").write_text("{}")
    (tmp_path / "short_interest.json").write_text("{}")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "analyst_consensus.json": {"generated_at": "2000-01-01T00:00:00+00:00", "count": 300, "coverage": 1.0},
    }))
    monkeypatch.setattr(status_service, "SCREENER_DIR", tmp_path)
    rows = {r["file"]: r for r in status_service.cache_freshness()}
    assert rows["analyst_consensus.json"]["state"] == "stale" and not rows["analyst_consensus.json"]["approx"]
    assert rows["short_interest.json"]["state"] == "ok" and rows["short_interest.json"]["approx"]
    assert rows["fundamentals.json"]["state"] == "missing"


def test_configured_keys_never_expose_values(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-secret")
    rows = status_service.configured_keys()
    assert {"key", "purpose", "set"} == set(rows[0])
    assert "gsk-secret" not in json.dumps(rows)
    assert next(r for r in rows if r["key"] == "GROQ_API_KEY")["set"]


# ── cache build safety gate ───────────────────────────────────────────────────

@pytest.mark.parametrize("count, expected, previous, ok", [
    (300, 300, 300, True),
    (271, 300, 300, True),     # 90% coverage, shrink 9.7%
    (200, 300, 0, False),      # 67% coverage
    (295, 300, 400, False),    # coverage fine, but shrank 26% vs previous file
])
def test_check_coverage(count, expected, previous, ok):
    assert (_common.check_coverage(count, expected, previous, 0.9, 0.1) is None) == ok


def test_write_cache_refuses_and_keeps_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "MANIFEST", tmp_path / "manifest.json")
    target = tmp_path / "x.json"
    good = {f"T{i}": {} for i in range(100)}
    assert _common.write_cache(target, good, expected=100, exit_on_refusal=False)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["x.json"]["count"] == 100

    assert not _common.write_cache(target, {"T0": {}}, expected=100, exit_on_refusal=False)
    assert len(json.loads(target.read_text())) == 100   # untouched

    with pytest.raises(SystemExit):
        _common.write_cache(target, {}, expected=100)
