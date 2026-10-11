"""
Type-ahead ticker search for the Stock Analyzer.

The index is every symbol in the nightly market snapshot (all US stocks and ETFs
with price data), plus anything extra in the local universe listing. It is
ranked locally, with no network call, so it is fast enough to run on every
keystroke.

Ranking (lower tier wins; ties go to the more heavily traded symbol):
  0 exact symbol · 1 symbol prefix · 2 name prefix · 3 a word in the name starts
  with the query · then close spellings (typo fallback) · 4 name contains the
  query — fuzzy and "contains" only fill slots the stronger tiers leave empty
Example: "apple" → AAPL (Apple Inc., name prefix, most traded) before APLE.
"""

import difflib
import re
import threading
import time

from stockiq.backend.data.market_snapshot import load_market_snapshot
from stockiq.backend.data.universe import _load_listing

_REBUILD_SECONDS = 1800
_lock = threading.Lock()
_index: list[dict] = []
_built_at = 0.0
_WORD = re.compile(r"[A-Z0-9]+")


def _entry(symbol: str, name, exchange, is_etf, dvol: float) -> dict:
    name = name if isinstance(name, str) and name.strip() else symbol       # NaN / None in older files
    exchange = exchange if isinstance(exchange, str) else ""
    upper = name.upper()
    return {
        "symbol": symbol, "name": name, "exchange": exchange or "", "is_etf": bool(is_etf),
        "dvol": dvol, "_name": upper, "_words": _WORD.findall(upper),
    }


def build_index(snapshot=None, listing: list[dict] | None = None) -> list[dict]:
    """Merge snapshot rows (with liquidity) and listing rows (without) into one index."""
    snapshot = load_market_snapshot() if snapshot is None else snapshot
    listing = _load_listing() if listing is None else listing
    out: dict[str, dict] = {}
    if snapshot is not None and not snapshot.empty:
        for r in snapshot[["symbol", "name", "exchange", "is_etf", "dollar_vol_20"]].itertuples(index=False):
            try:
                dvol = float(r.dollar_vol_20)
                dvol = dvol if dvol == dvol else 0.0                                # NaN → 0
            except (TypeError, ValueError):
                dvol = 0.0
            if isinstance(r.symbol, str) and r.symbol:
                out[r.symbol] = _entry(r.symbol, r.name, r.exchange, r.is_etf == r.is_etf and bool(r.is_etf), dvol)
    for s in listing:
        if s["symbol"] not in out:
            out[s["symbol"]] = _entry(s["symbol"], s["name"], s["exchange"], s["is_etf"], 0.0)
    return list(out.values())


def _get_index() -> list[dict]:
    global _index, _built_at
    if _index and time.time() - _built_at < _REBUILD_SECONDS:
        return _index
    with _lock:
        if not _index or time.time() - _built_at >= _REBUILD_SECONDS:
            _index, _built_at = build_index(), time.time()
    return _index


_fuzzy_keys: tuple[int, dict[str, list[dict]], list[str]] | None = None


def _fuzzy_table(index: list[dict]) -> tuple[dict[str, list[dict]], list[str]]:
    """{first word of name or symbol: entries (most traded first)}, built once per index."""
    global _fuzzy_keys
    if _fuzzy_keys is None or _fuzzy_keys[0] != id(index):
        by_key: dict[str, list[dict]] = {}
        for e in sorted(index, key=lambda e: -e["dvol"]):
            if e["_words"]:
                by_key.setdefault(e["_words"][0], []).append(e)
            by_key.setdefault(e["symbol"], []).append(e)
        _fuzzy_keys = (id(index), by_key, list(by_key))
    return _fuzzy_keys[1], _fuzzy_keys[2]


def _fuzzy(q: str, q_sym: str, index: list[dict], exclude: set[str], n: int) -> list[dict]:
    """Close spellings of the name's first word or the symbol (difflib)."""
    by_key, keys = _fuzzy_table(index)
    close = difflib.get_close_matches(q, keys, n=n * 3, cutoff=0.75)
    close += [k for k in difflib.get_close_matches(q_sym, keys, n=n * 3, cutoff=0.75) if k not in close]
    found: dict[str, dict] = {}
    for k in close:
        for e in by_key[k]:
            if e["symbol"] not in exclude:
                found.setdefault(e["symbol"], e)
    return list(found.values())[:n]


def rank_symbols(query: str, index: list[dict], limit: int = 5) -> list[dict]:
    """Best `limit` matches for `query` (pure — tests pass their own index)."""
    q = query.strip().upper()
    if not q:
        return []
    q_sym = q.replace(".", "-").replace(" ", "")
    hits: list[tuple[int, float, str, dict]] = []
    for e in index:
        sym, name = e["symbol"], e["_name"]
        if sym == q_sym:
            tier = 0
        elif sym.startswith(q_sym):
            tier = 1
        elif name.startswith(q):
            tier = 2
        elif any(w.startswith(q) for w in e["_words"]):
            tier = 3
        elif q in name:
            tier = 4
        else:
            continue
        hits.append((tier, -e["dvol"], sym, e))
    hits.sort(key=lambda h: h[:3])
    strong = [h[3] for h in hits if h[0] <= 3][:limit]
    weak = [h[3] for h in hits if h[0] == 4]

    results = strong
    if len(results) < limit and len(q) >= 3:            # typo fallback, e.g. "aple" → Apple Inc.
        results += _fuzzy(q, q_sym, index, {e["symbol"] for e in results}, limit - len(results))
    seen = {e["symbol"] for e in results}
    results += [e for e in weak if e["symbol"] not in seen][:limit - len(results)]

    return [{"symbol": e["symbol"], "name": _display_name(e["name"]), "exchange": e["exchange"],
             "type": "ETF" if e["is_etf"] else "EQUITY"} for e in results[:limit]]


def _display_name(name: str) -> str:
    """'Apple Inc. - Common Stock' → 'Apple Inc.'"""
    return " ".join(name.split(" - ")[0].split())


def symbol_names() -> dict[str, str]:
    """symbol → short company name for every symbol in the index."""
    return {e["symbol"]: _display_name(e["name"]) for e in _get_index()}


def suggest_symbols(query: str, limit: int = 5) -> list[dict]:
    """Top `limit` matches across all US listings with price data."""
    return rank_symbols(query, _get_index(), limit)
