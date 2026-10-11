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
