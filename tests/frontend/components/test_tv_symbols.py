"""Yahoo → TradingView symbol translation for the analyzer chart."""

import pytest

from stockiq.frontend.views.components.tv_symbols import to_tradingview_symbol


@pytest.mark.parametrize("yahoo, tv", [
    ("AAPL", "AAPL"),
    ("spy", "SPY"),
    ("BRK-B", "BRK.B"),
    ("BTC-USD", "BTCUSD"),
    ("ETH-USDT", "ETHUSDT"),
    ("EURUSD=X", "FX:EURUSD"),
    ("JPY=X", "FX:USDJPY"),
    ("ES=F", "ES1!"),
    ("^GSPC", "SP:SPX"),
    ("^VIX", "CBOE:VIX"),
    ("^SOMEINDEX", "SOMEINDEX"),
    ("0700.HK", "HKEX:700"),
    ("RY.TO", "TSX:RY"),
    ("RELIANCE.NS", "NSE:RELIANCE"),
    ("SAP.DE", "XETR:SAP"),
    ("XYZ.QQ", "XYZ.QQ"),      # unknown suffix passes through
    ("", ""),
])
def test_to_tradingview_symbol(yahoo, tv):
    assert to_tradingview_symbol(yahoo) == tv
