"""
Render every Streamlit page with all network access blocked.

Market-data outages are the most common real-world failure for this app; every
page must degrade to a message, never a traceback. Blocking sockets also makes
the test fast and deterministic in CI.
"""

import socket
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import stockiq.backend.cache as cache_mod

VIEWS = Path(__file__).resolve().parents[2] / "src" / "stockiq" / "frontend" / "views"
PAGES = sorted(p for p in VIEWS.glob("*.py") if p.name != "__init__.py")


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def refuse(*_a, **_k):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setenv("STOCKIQ_DATA_DIR", str(tmp_path))
    cache_mod.clear_caches()
    yield
    cache_mod.clear_caches()


@pytest.mark.parametrize("page", PAGES, ids=[p.stem for p in PAGES])
def test_page_renders_without_exception_when_offline(page):
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception, f"{page.name}: {at.exception[0].message}"


def test_analyzer_ticker_is_sanitised_before_reaching_the_chart():
    at = AppTest.from_file(str(VIEWS / "analyzer.py"), default_timeout=60)
    at.query_params["tic"] = 'AAPL"});alert(1);//'
    at.run()
    assert not at.exception
    value = at.text_input[1].value
    assert value == "AAPLALERT1"                     # letters/digits kept …
    assert not set(value) & set('"\'();/{}<> ')    # … nothing that can break out of the JS string


def test_market_screener_renders_with_data(monkeypatch):
    import pandas as pd

    import stockiq.backend.services.market_screener_service as svc
    from stockiq.backend.market.snapshot import SNAPSHOT_COLUMNS, snapshot_row
    from tests.conftest import _make_ohlcv

    rows = []
    for i in range(8):
        df = _make_ohlcv(n=1200, base_price=30 + 20 * i, seed=i)
        df.index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=1200)
        rows.append(snapshot_row(f"S{i}", df, {"name": f"Co {i}", "exchange": "NYSE", "is_etf": i % 3 == 0}))
    monkeypatch.setattr(svc, "load_market_snapshot", lambda: pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS))

    at = AppTest.from_file(str(VIEWS / "market_screener.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    assert at.metric[0].value == "8"
    assert len(at.dataframe) == 1
    at.selectbox[0].set_value("Oversold (RSI ≤ 30)").run()
    assert not at.exception
