"""Type-ahead ticker search: index build and ranking — network-free."""

import pandas as pd

from stockiq.backend.data.symbol_search import build_index, rank_symbols

ROWS = [
    # symbol, name, exchange, is_etf, 20-day $ volume
    ("AAPL", "Apple Inc. - Common Stock", "NASDAQ", False, 9e9),
    ("APLE", "Apple Hospitality REIT, Inc. Common Shares", "NYSE", False, 5e7),
    ("AMAT", "Applied Materials, Inc. - Common Stock", "NASDAQ", False, 2e9),
    ("MSFT", "Microsoft Corporation - Common Stock", "NASDAQ", False, 8e9),
    ("MU", "Micron Technology, Inc. - Common Stock", "NASDAQ", False, 3e9),
    ("AMD", "Advanced Micro Devices, Inc. - Common Stock", "NASDAQ", False, 6e9),
    ("BAC", "Bank of America Corporation Common Stock", "NYSE", False, 1e9),
    ("BRK-B", "Berkshire Hathaway Inc. Class B", "NYSE", False, 1e9),
    ("XLP", "Consumer Staples Select Sector SPDR", "NYSE ARCA", True, 7e8),
    ("SPY", "SPDR S&P 500 ETF Trust", "NYSE ARCA", True, 3e10),
    ("SPYG", "SPDR Portfolio S&P 500 Growth ETF", "NYSE ARCA", True, 2e8),
]


def _index():
    snap = pd.DataFrame(ROWS, columns=["symbol", "name", "exchange", "is_etf", "dollar_vol_20"])
    return build_index(snap, [{"symbol": "ZZZ", "name": "Listing Only Co", "exchange": "NYSE", "is_etf": False}])


def _syms(q, **kw):
    return [r["symbol"] for r in rank_symbols(q, _index(), **kw)]


def test_index_merges_snapshot_and_listing():
    syms = {e["symbol"] for e in _index()}
    assert {"AAPL", "ZZZ"} <= syms and len(syms) == len(ROWS) + 1


def test_exact_symbol_first_then_prefix_by_liquidity():
    assert _syms("spy") == ["SPY", "SPYG"]
    assert _syms("aapl")[0] == "AAPL"


def test_company_name_most_traded_first():
    assert _syms("apple")[:2] == ["AAPL", "APLE"]
    assert _syms("micro")[:3] == ["MSFT", "MU", "AMD"]       # name prefix before word prefix


def test_multi_word_and_dotted_symbols():
    assert _syms("bank of am") == ["BAC"]
    assert _syms("brk.b")[0] == "BRK-B"


def test_typo_fallback_beats_weak_contains():
    assert _syms("aple")[:2] == ["APLE", "AAPL"]               # exact symbol, then "Apple" spelled wrong
    assert "MSFT" in _syms("microsfot")


def test_limit_and_shape():
    out = rank_symbols("a", _index(), limit=5)
    assert len(out) == 5
    assert set(out[0]) == {"symbol", "name", "exchange", "type"}
    assert rank_symbols("spy", _index())[0]["type"] == "ETF"
    assert rank_symbols("aapl", _index())[0]["name"] == "Apple Inc."   # " - Common Stock" trimmed
    assert rank_symbols("   ", _index()) == []


def test_service_falls_back_to_yahoo_when_local_has_nothing(monkeypatch):
    import stockiq.backend.services.analyzer_service as svc

    monkeypatch.setattr(svc, "suggest_symbols", lambda q, limit: [])
    monkeypatch.setattr(svc, "search_companies", lambda q: [
        {"symbol": "MSFT", "name": "Microsoft", "exchange": "NMS", "type": "EQUITY"}])
    svc._yahoo_suggest.clear()
    assert svc.suggest_tickers("msft")[0]["symbol"] == "MSFT"
    assert svc.suggest_tickers("m") == []                      # 1 letter: no network call
    svc._yahoo_suggest.clear()


def test_old_snapshot_with_missing_names_still_indexes():
    old = pd.DataFrame({"symbol": ["MSFT"], "name": [None], "exchange": [None],
                        "is_etf": [None], "dollar_vol_20": [None]})
    assert rank_symbols("msft", build_index(old, []))[0]["symbol"] == "MSFT"
