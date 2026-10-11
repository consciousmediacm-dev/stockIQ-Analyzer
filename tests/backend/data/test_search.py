"""Symbol search: local all-US listing merged with Yahoo search."""

from unittest.mock import MagicMock, patch

import pytest

import stockiq.backend.data.universe as universe
from stockiq.backend.data.yf_fetch import search_companies

_LISTING = [
    {"symbol": "AAPL", "name": "Apple Inc. - Common Stock", "exchange": "NASDAQ", "is_etf": False},
    {"symbol": "APLE", "name": "Apple Hospitality REIT", "exchange": "NYSE", "is_etf": False},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway Inc. Class B", "exchange": "NYSE", "is_etf": False},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "NYSE Arca", "is_etf": True},
    {"symbol": "PINE", "name": "Alpine Income Property Trust", "exchange": "NYSE", "is_etf": False},
]


@pytest.fixture(autouse=True)
def listing(monkeypatch):
    monkeypatch.setattr(universe, "_cache", list(_LISTING))


def test_search_universe_ranks_symbol_then_name():
    syms = [r["symbol"] for r in universe.search_universe("apple")]
    assert syms[:2] == ["AAPL", "APLE"]            # name prefix beats name-contains
    assert universe.search_universe("aapl")[0]["symbol"] == "AAPL"
    assert universe.search_universe("brk.b")[0]["symbol"] == "BRK-B"   # dot form accepted
    assert universe.search_universe("spy")[0]["type"] == "ETF"
    assert universe.search_universe("") == []


def test_get_universe_lists():
    assert universe.get_universe("us_etfs") == ["SPY"]
    assert "AAPL" in universe.get_universe("us_equities") and "SPY" not in universe.get_universe("us_equities")
    with pytest.raises(ValueError):
        universe.get_universe("nope")


def _yahoo(quotes):
    m = MagicMock()
    m.quotes = quotes
    return m


@patch("stockiq.backend.data.yf_fetch.yf.Search")
def test_search_includes_crypto_fx_futures(mock_search):
    mock_search.return_value = _yahoo([
        {"symbol": "BTC-USD", "shortname": "Bitcoin USD", "exchange": "CCC", "quoteType": "CRYPTOCURRENCY"},
        {"symbol": "EURUSD=X", "shortname": "EUR/USD", "exchange": "CCY", "quoteType": "CURRENCY"},
        {"symbol": "ES=F", "shortname": "E-Mini S&P 500", "exchange": "CME", "quoteType": "FUTURE"},
        {"symbol": "XNEWS", "shortname": "news", "exchange": "", "quoteType": "NEWS"},
    ])
    syms = [r["symbol"] for r in search_companies("bitcoin")]
    assert {"BTC-USD", "EURUSD=X", "ES=F"} <= set(syms) and "XNEWS" not in syms


@patch("stockiq.backend.data.yf_fetch.yf.Search")
def test_search_merges_local_when_yahoo_fails(mock_search):
    mock_search.side_effect = ConnectionError("blocked")
    syms = [r["symbol"] for r in search_companies("apple")]
    assert syms[:2] == ["AAPL", "APLE"]


@patch("stockiq.backend.data.yf_fetch.yf.Search")
def test_search_exact_symbol_first_and_deduped(mock_search):
    mock_search.return_value = _yahoo([
        {"symbol": "SPYG", "shortname": "SPDR Growth", "exchange": "PCX", "quoteType": "ETF"},
        {"symbol": "SPY", "shortname": "SPDR S&P 500", "exchange": "PCX", "quoteType": "ETF"},
    ])
    results = search_companies("SPY")
    syms = [r["symbol"] for r in results]
    assert syms[0] == "SPY" and syms.count("SPY") == 1
