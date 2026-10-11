"""Tests for the TTL cache layer and forecast cache keying."""

import threading
import time

import pandas as pd

from stockiq.backend.cache import (
    MemoryCache,
    SqliteCache,
    clear_caches,
    is_empty_result,
    ttl_cache,
)
from stockiq.backend.llm.providers import forecast_store_key


def test_memory_cache_is_lru_bounded():
    c = MemoryCache(max_entries=2)
    c.set("a", 1, 60)
    c.set("b", 2, 60)
    c.get("a")            # a is now most recent
    c.set("c", 3, 60)     # evicts b
    assert c.get("a") == (1, True)
    assert c.get("b") == (None, False)
    assert len(c) == 2


def test_memory_cache_expires():
    c = MemoryCache()
    c.set("a", 1, -1)
    assert c.get("a") == (None, False)


def test_empty_results_use_short_negative_ttl():
    calls = []

    @ttl_cache(3600, backend=MemoryCache(), negative_ttl=0)
    def fetch(x):
        calls.append(x)
        return pd.DataFrame()

    fetch(1)
    fetch(1)
    assert len(calls) == 2   # empty result not cached when negative_ttl=0


def test_non_empty_results_are_cached_and_exceptions_are_not():
    calls = []

    @ttl_cache(3600, backend=MemoryCache())
    def fetch(x):
        calls.append(x)
        if x == "boom":
            raise RuntimeError("down")
        return {"v": x}

    assert fetch("a") == {"v": "a"} and fetch("a") == {"v": "a"}
    assert calls == ["a"]
    for _ in range(2):
        try:
            fetch("boom")
        except RuntimeError:
            pass
    assert calls.count("boom") == 2


def test_single_flight_under_concurrency():
    calls = []

    @ttl_cache(3600, backend=MemoryCache())
    def slow(x):
        calls.append(x)
        time.sleep(0.2)
        return [x]

    threads = [threading.Thread(target=slow, args=(1,)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == [1]


def test_clear_caches_by_prefix():
    calls = []

    @ttl_cache(3600)
    def probe():
        calls.append(1)
        return [1]

    probe()
    probe()
    assert clear_caches(f"{__name__}.") >= 1
    probe()
    assert len(calls) == 2


def test_is_empty_result():
    assert is_empty_result(None) and is_empty_result({}) and is_empty_result([])
    assert is_empty_result(pd.DataFrame()) and is_empty_result(pd.Series(dtype=float))
    assert not is_empty_result({"a": 1}) and not is_empty_result(0)
    assert not is_empty_result(pd.DataFrame({"a": [1]}))


def test_sqlite_cache_roundtrip_and_namespaces(tmp_path):
    path = tmp_path / "c.sqlite"
    a, b = SqliteCache("a", path), SqliteCache("b", path)
    df = pd.DataFrame({"x": [1, 2]})
    a.set("k", df, 60)
    got, hit = SqliteCache("a", path).get("k")   # survives a new instance (restart)
    assert hit and got.equals(df)
    assert b.get("k") == (None, False)
    a.set("old", 1, -1)
    assert a.get("old") == (None, False)
    a.clear()
    assert a.get("k") == (None, False)


def test_personal_key_forecasts_are_namespaced():
    shared = forecast_store_key("2026-10-11-10", "groq")
    mine = forecast_store_key("2026-10-11-10", "groq", "sk-secret")
    theirs = forecast_store_key("2026-10-11-10", "groq", "sk-other")
    assert len({shared, mine, theirs}) == 3
    assert "sk-secret" not in mine
