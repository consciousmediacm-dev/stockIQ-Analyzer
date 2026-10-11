"""
Process-level cache abstraction.

CacheBackend — protocol that all cache implementations must satisfy.
MemoryCache  — in-process, thread-safe, size-bounded (LRU) TTL cache. Default.
SqliteCache  — on-disk TTL cache that survives restarts (pickled values).

Pick the default backend with STOCKIQ_CACHE_BACKEND=memory|sqlite
(sqlite file lives in STOCKIQ_DATA_DIR, default ~/.stockiq). A RedisCache can
implement the same protocol later without touching decorated functions.

ttl_cache behaviour:
  • Empty results (None, empty DataFrame/dict/list) are cached only briefly
    (negative_ttl, default 30 s) so a provider outage doesn't blank a page for
    the full TTL, but a hard-down source still isn't hammered on every rerun.
  • Exceptions are never cached.
  • Single-flight: concurrent callers with the same key wait for one
    computation instead of all hitting the data provider at once.

Usage:
    from stockiq.backend.cache import ttl_cache

    @ttl_cache(60)
    def my_fn(arg): ...

    my_fn.clear()                     # clear one function's cache
    clear_caches("stockiq.backend.data.spy")   # clear every cache in a module
"""

import functools
import hashlib
import logging
import os
import pickle
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("STOCKIQ_DATA_DIR") or Path.home() / ".stockiq")


@runtime_checkable
class CacheBackend(Protocol):
    """Minimal interface required by ttl_cache and future cache backends."""

    def get(self, key: str) -> tuple[Any, bool]:
        """Return (value, hit). hit=False means key missing or expired."""
        ...

    def set(self, key: str, value: Any, ttl: int) -> None:
        """Store value under key for ttl seconds."""
        ...

    def delete(self, key: str) -> None:
        """Remove a single key (no-op if absent)."""
        ...

    def clear(self) -> None:
        """Remove all entries."""
        ...


class MemoryCache:
    """In-process TTL cache: thread-safe, LRU-bounded to max_entries.

    Each decorated function gets its own MemoryCache instance by default,
    so caches are isolated. Pass a shared instance to bridge two functions.
    """

    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max_entries
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> tuple[Any, bool]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None, False
            value, expires = entry
            if time.time() < expires:
                self._store.move_to_end(key)
                return value, True
            del self._store[key]
            return None, False

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            self._store[key] = (value, time.time() + ttl)
            self._store.move_to_end(key)
            self._evict()

    def _evict(self) -> None:
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if exp <= now]
        for k in expired:
            del self._store[k]
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


class SqliteCache:
    """On-disk TTL cache in one SQLite file; one table namespace per instance."""

    def __init__(self, namespace: str, path: Path | None = None) -> None:
        self.namespace = namespace
        self.path = path or DATA_DIR / "cache.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS cache (ns TEXT, key TEXT, value BLOB, expires REAL, "
                "PRIMARY KEY (ns, key))"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def get(self, key: str) -> tuple[Any, bool]:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT value, expires FROM cache WHERE ns=? AND key=?", (self.namespace, key)
            ).fetchone()
            if row is None:
                return None, False
            if row[1] <= time.time():
                c.execute("DELETE FROM cache WHERE ns=? AND key=?", (self.namespace, key))
                return None, False
        try:
            return pickle.loads(row[0]), True
        except Exception:
            return None, False

    def set(self, key: str, value: Any, ttl: int) -> None:
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)",
                (self.namespace, key, blob, time.time() + ttl),
            )
            c.execute("DELETE FROM cache WHERE expires <= ?", (time.time(),))

    def delete(self, key: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM cache WHERE ns=? AND key=?", (self.namespace, key))

    def clear(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM cache WHERE ns=?", (self.namespace,))


def default_backend(namespace: str) -> CacheBackend:
    if os.environ.get("STOCKIQ_CACHE_BACKEND", "memory").lower() == "sqlite":
        return SqliteCache(namespace)
    return MemoryCache()


def is_empty_result(value: Any) -> bool:
    """None, empty DataFrame/Series, or empty dict/list/tuple."""
    if value is None:
        return True
    empty = getattr(value, "empty", None)
    if isinstance(empty, bool):
        return empty
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) == 0
    return False


def make_key(args: tuple, kwargs: dict) -> str:
    raw = repr(args) + repr(sorted(kwargs.items()))
    return raw if len(raw) <= 200 else hashlib.sha256(raw.encode()).hexdigest()


# name → cache-clearing function, for clear_caches() / the health page
_REGISTRY: dict[str, Callable[[], None]] = {}


def clear_caches(prefix: str = "") -> int:
    """Clear every ttl_cache whose qualified name starts with prefix. Returns how many."""
    names = [n for n in _REGISTRY if n.startswith(prefix)]
    for n in names:
        _REGISTRY[n]()
    return len(names)


def registered_caches() -> list[str]:
    return sorted(_REGISTRY)


def ttl_cache(ttl_seconds: int, backend: CacheBackend | None = None, negative_ttl: int = 30):
    """Decorator that caches the return value for ``ttl_seconds`` seconds.

    Args:
        ttl_seconds:  How long to keep non-empty results.
        backend:      CacheBackend to use. Defaults to default_backend() per
                      decorated function (isolated caches).
        negative_ttl: How long to keep empty results (see is_empty_result).
                      0 disables caching of empty results entirely.
    """
    def decorator(fn):
        name = f"{fn.__module__}.{fn.__qualname__}"
        _backend: CacheBackend = backend if backend is not None else default_backend(name)
        key_locks: dict[str, threading.Lock] = {}
        locks_guard = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = make_key(args, kwargs)
            value, hit = _backend.get(key)
            if hit:
                return value
            with locks_guard:
                lock = key_locks.setdefault(key, threading.Lock())
            with lock:
                value, hit = _backend.get(key)   # another thread may have filled it
                if hit:
                    return value
                result = fn(*args, **kwargs)
                ttl = min(negative_ttl, ttl_seconds) if is_empty_result(result) else ttl_seconds
                if ttl > 0:
                    _backend.set(key, result, ttl)
                return result

        wrapper.clear = _backend.clear  # type: ignore[attr-defined]
        wrapper.cache_backend = _backend  # type: ignore[attr-defined]
        _REGISTRY[name] = _backend.clear
        return wrapper

    return decorator
