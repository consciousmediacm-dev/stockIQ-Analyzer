"""Tests for the provider layer, validation, Alpha Vantage parsing and universes — network-free."""

from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

import stockiq.backend.data.providers as providers
from stockiq.backend.data.providers.alphavantage import (
    AlphaVantageProvider,
    parse_daily_csv,
    parse_global_quote,
)
from stockiq.backend.data.providers.base import (
    ProviderError,
    ProviderNotConfigured,
    RateLimitError,
    with_retry,
)
from stockiq.backend.data.providers.validation import validate_ohlcv
from stockiq.backend.data.spy import _cboe_ts
from stockiq.backend.data.universe import parse_av_listing, parse_nasdaq_traded


def _bars(n=30, start="2026-01-02", price=100.0):
    idx = pd.bdate_range(start, periods=n)
    close = price + np.arange(n, dtype=float)
    return pd.DataFrame(
        {"Open": close - 0.5, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1e6},
        index=idx,
    )


# ── with_retry ────────────────────────────────────────────────────────────────

def test_with_retry_backs_off_then_succeeds():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ProviderError("boom")
        return "ok"

    assert with_retry(flaky, attempts=3, base_delay=1, sleep=sleeps.append) == "ok"
    assert sleeps == [1, 2]


def test_with_retry_gives_up_and_never_retries_missing_config():
    with pytest.raises(ProviderError):
        with_retry(lambda: (_ for _ in ()).throw(ProviderError("x")), attempts=2, sleep=lambda s: None)
    calls = []

    def unconfigured():
        calls.append(1)
        raise ProviderNotConfigured("no key")

    with pytest.raises(ProviderNotConfigured):
        with_retry(unconfigured, attempts=3, sleep=lambda s: None)
    assert len(calls) == 1


# ── validation ────────────────────────────────────────────────────────────────

def test_validate_repairs_and_flags():
    df = _bars(10)
    df.iloc[3, df.columns.get_loc("Close")] = 0            # bad close → dropped
    df.iloc[5, df.columns.get_loc("High")] = df["Low"].iloc[5] - 5  # inverted → repaired
    df = pd.concat([df, df.iloc[[2]]])                       # duplicate date → dropped
    res = validate_ohlcv(df, "X")
    assert res.usable
    assert len(res.df) == 9
    assert res.df.index.is_monotonic_increasing and not res.df.index.duplicated().any()
    assert (res.df["High"] >= res.df[["Open", "Close"]].max(axis=1)).all()
    assert any("duplicate" in i for i in res.issues)
    assert any("non-positive" in i for i in res.issues)
    assert any("High/Low" in i for i in res.issues)


def test_validate_flags_unadjusted_split_and_staleness():
    df = _bars(20)
    df.loc[df.index[10]:, ["Open", "High", "Low", "Close"]] /= 4   # 4:1 split, unadjusted
    res = validate_ohlcv(df, "X", max_stale_days=3, today=date(2026, 6, 1))
    assert any("unadjusted split" in i for i in res.issues)
    assert not res.usable  # last bar in January, 'today' is June


def test_validate_empty_is_unusable():
    assert not validate_ohlcv(pd.DataFrame(), "X").usable


# ── failover chain ────────────────────────────────────────────────────────────

class _Fake:
    def __init__(self, name, data=None, exc=None, configured=True):
        self.name, self._data, self._exc, self._cfg = name, data or {}, exc, configured
        self.requested: list[list[str]] = []

    def is_configured(self):
        return self._cfg

    def daily_history(self, tickers, start, end):
        self.requested.append(list(tickers))
        if self._exc:
            raise self._exc
        return {t: df for t, df in self._data.items() if t in tickers}


@pytest.fixture
def fake_chain(monkeypatch):
    def install(*fakes):
        monkeypatch.setattr(providers, "_instances", {f.name: f for f in fakes})
        monkeypatch.setattr(providers, "_FACTORIES", {f.name: type(f) for f in fakes})
        monkeypatch.setattr(providers, "_status", {})
        monkeypatch.setattr(providers, "_down_until", {})
        return [f.name for f in fakes]
    return install


def test_failover_fills_only_missing_tickers(fake_chain):
    a = _Fake("a", {"AAA": _bars()})
    b = _Fake("b", {"AAA": _bars(price=999), "BBB": _bars()})
    order = fake_chain(a, b)
    out = providers.get_daily_history(["AAA", "BBB", "ZZZ"], date(2026, 1, 1), providers=order)
    assert set(out) == {"AAA", "BBB"}
    assert out["AAA"]["Close"].iloc[0] == 100.0        # served by first provider
    assert b.requested == [["BBB", "ZZZ"]]             # second only asked for the gaps


def test_failover_on_provider_error_and_skips_unconfigured(fake_chain):
    a = _Fake("a", exc=ProviderError("down"))
    b = _Fake("b", {"AAA": _bars()}, configured=False)
    c = _Fake("c", {"AAA": _bars()})
    order = fake_chain(a, b, c)
    out = providers.get_daily_history(["AAA"], date(2026, 1, 1), providers=order)
    assert "AAA" in out
    assert b.requested == []
    status = providers._status
    assert status["a"].failures >= 1 and status["c"].tickers_served == 1
    assert providers._is_down("a")          # hard failure opens the breaker


def test_unusable_data_falls_through(fake_chain):
    a = _Fake("a", {"AAA": pd.DataFrame({"Close": [np.nan]}, index=[pd.Timestamp("2026-01-02")])})
    b = _Fake("b", {"AAA": _bars()})
    out = providers.get_daily_history(["AAA"], date(2026, 1, 1), providers=fake_chain(a, b))
    assert len(out["AAA"]) == 30


# ── Alpha Vantage ─────────────────────────────────────────────────────────────

_AV_DAILY = (
    "timestamp,open,high,low,close,volume\r\n"
    "2026-10-09,225.8700,228.7600,224.0501,227.1300,3352852\r\n"
    "2026-10-08,220.1500,227.3050,217.7950,226.6100,8929853\r\n"
)
_AV_ADJ = (
    "timestamp,open,high,low,close,adjusted_close,volume,dividend_amount,split_coefficient\n"
    "2026-10-09,200,210,190,200,100,1000,0.0,1.0\n"
    "2026-10-08,100,110,90,100,100,1000,0.0,2.0\n"
)


def test_parse_daily_csv_raw_sorted_ascending():
    df = parse_daily_csv(_AV_DAILY)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.index[0] == pd.Timestamp("2026-10-08")
    assert df["Close"].iloc[-1] == pytest.approx(227.13)


def test_parse_daily_csv_adjusted_scales_ohlc():
    df = parse_daily_csv(_AV_ADJ)
    last = df.loc["2026-10-09"]
    assert last["Close"] == 100 and last["Open"] == 100 and last["High"] == 105 and last["Low"] == 95


def test_parse_global_quote():
    q = parse_global_quote({"Global Quote": {
        "01. symbol": "SPY", "02. open": "776.2400", "03. high": "779.4200", "04. low": "775.1400",
        "05. price": "778.5700", "06. volume": "22624488", "07. latest trading day": "2026-10-09",
        "08. previous close": "773.9300", "09. change": "4.6400", "10. change percent": "0.5995%",
    }})
    assert q["price"] == 778.57 and q["change_pct"] == 0.5995 and q["volume"] == 22624488
    assert q["_ts"] > 0
    assert parse_global_quote({}) == {}


def _resp(text, status=200):
    r = MagicMock()
    r.status_code, r.text = status, text
    r.json.side_effect = lambda: __import__("json").loads(text)
    r.raise_for_status.return_value = None
    return r


def test_alphavantage_detects_premium_and_rate_limit_messages():
    session = MagicMock()
    session.get.return_value = _resp('{"Information": "Thank you for using Alpha Vantage! This is a premium endpoint."}')
    av = AlphaVantageProvider(api_key="k", premium=False, requests_per_minute=6000, session=session)
    with pytest.raises(RateLimitError):
        av.daily_history(["IBM"], date(2026, 1, 1), date(2026, 10, 9))


def test_alphavantage_uses_adjusted_endpoint_only_on_premium():
    session = MagicMock()
    session.get.return_value = _resp(_AV_DAILY)
    AlphaVantageProvider(api_key="k", premium=False, requests_per_minute=6000, session=session) \
        .daily_history(["BRK-B"], date(2026, 10, 1), date(2026, 10, 9))
    params = session.get.call_args.kwargs["params"]
    assert params["function"] == "TIME_SERIES_DAILY" and params["symbol"] == "BRK.B"

    session.get.return_value = _resp(_AV_ADJ)
    AlphaVantageProvider(api_key="k", premium=True, requests_per_minute=6000, session=session) \
        .daily_history(["IBM"], date(2026, 10, 1), date(2026, 10, 9))
    assert session.get.call_args.kwargs["params"]["function"] == "TIME_SERIES_DAILY_ADJUSTED"


def test_alphavantage_unconfigured():
    assert not AlphaVantageProvider(api_key="").is_configured()


# ── CBOE timestamp ────────────────────────────────────────────────────────────

def test_cboe_timestamp_is_eastern_time():
    # 2026-10-09 16:00 ET == 20:00 UTC (EDT, UTC-4)
    assert _cboe_ts("2026-10-09T16:00:00") == int(pd.Timestamp("2026-10-09 20:00", tz="UTC").timestamp())
    assert _cboe_ts("garbage") == 0


# ── Universes ─────────────────────────────────────────────────────────────────

_NASDAQ_TRADED = """Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares
Y|AAPL|Apple Inc. - Common Stock|Q|Q|N|100|N|N||AAPL|N
Y|BRK.B|Berkshire Hathaway Inc. Class B|N| |N|100|N||BRK.B|BRK.B|N
Y|SPY|SPDR S&P 500 ETF Trust|P| |Y|100|N||SPY|SPY|N
Y|ABCDW|ABCD Corp - Warrants|Q|G|N|100|N|N||ABCDW|N
Y|XYZ$A|XYZ Corp 6% Preferred Series A|N| |N|100|N||XYZ$A|XYZ$A|N
Y|ZVZZT|NASDAQ TEST STOCK|Q|G|N|100|Y|N||ZVZZT|N
Y|AHL-D|Aspen Insurance Holdings Limited 5.625% Perpetual Pref Shares|N| |N|100|N||AHLpD|AHL-D|N
Y|XYZWS|XYZ Corp Warrants to purchase|N| |N|100|N||XYZws|XYZ.WS|N
File Creation Time: 1010202620:01|||||||||||
"""


def test_parse_nasdaq_traded_filters_and_normalises():
    df = parse_nasdaq_traded(_NASDAQ_TRADED)
    assert list(df["symbol"]) == ["AAPL", "BRK-B", "SPY"]
    assert df.set_index("symbol").loc["SPY", "is_etf"]
    assert df.set_index("symbol").loc["AAPL", "exchange"] == "NASDAQ"


def test_parse_av_listing():
    raw = pd.DataFrame({
        "symbol": ["A", "BF.B", "QQQ", "OLD"], "name": ["Agilent", "Brown-Forman B", "Invesco QQQ", "Gone"],
        "exchange": ["NYSE", "NYSE", "NASDAQ", "NYSE"], "assetType": ["Stock", "Stock", "ETF", "Stock"],
        "status": ["Active", "Active", "Active", "Delisted"],
    })
    df = parse_av_listing(raw)
    assert list(df["symbol"]) == ["A", "BF-B", "QQQ"]
    assert df["is_etf"].tolist() == [False, False, True]


def test_validate_does_not_flag_normal_volatility():
    df = _bars(20)
    df.loc[df.index[10]:, ["Open", "High", "Low", "Close"]] *= 0.8   # −20% day: real, not a split
    assert not any("split" in i for i in validate_ohlcv(df, "X").issues)


# ── circuit breaker ───────────────────────────────────────────────────────────

def test_breaker_skips_provider_after_empty_batch(fake_chain, monkeypatch):
    monkeypatch.setattr(providers, "_down_until", {})
    a = _Fake("a", {})                       # reachable but returns nothing (yfinance offline)
    b = _Fake("b", {f"T{i}": _bars() for i in range(6)})
    order = fake_chain(a, b)
    tickers = [f"T{i}" for i in range(6)]
    assert len(providers.get_daily_history(tickers, date(2026, 1, 1), providers=order)) == 6
    assert len(a.requested) == 1
    providers.get_daily_history(tickers, date(2026, 1, 1), providers=order)
    assert len(a.requested) == 1            # skipped while the breaker is open
    assert providers.provider_status()["a"]["failures"] >= 1


def test_large_batches_probe_first(fake_chain, monkeypatch):
    monkeypatch.setattr(providers, "_down_until", {})
    a = _Fake("a", {})
    a.probe_symbol = "SPY"
    b = _Fake("b", {f"T{i}": _bars() for i in range(30)})
    order = fake_chain(a, b)
    out = providers.get_daily_history([f"T{i}" for i in range(30)], date(2026, 1, 1), providers=order)
    assert len(out) == 30
    assert a.requested == [["SPY"]]          # only the probe hit the dead provider
