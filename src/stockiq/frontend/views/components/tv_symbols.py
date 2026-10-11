"""
Translate Yahoo Finance symbols to TradingView symbols for the embedded chart.

Yahoo and TradingView spell many instruments differently:

    Yahoo        TradingView
    BRK-B        BRK.B           (US share classes)
    BTC-USD      BTCUSD          (crypto)
    EURUSD=X     FX:EURUSD       (currencies)
    ES=F         ES1!            (continuous front-month futures)
    ^GSPC        SP:SPX          (indices — common ones mapped, others best-effort)
    0700.HK      HKEX:700        (international listings by exchange suffix)

Unknown forms pass through unchanged, which is what TradingView expects for
plain US tickers like AAPL or SPY.
"""

_INDICES = {
    "^GSPC": "SP:SPX", "^SPX": "SP:SPX", "^DJI": "DJ:DJI", "^IXIC": "NASDAQ:IXIC",
    "^NDX": "NASDAQ:NDX", "^RUT": "TVC:RUT", "^VIX": "CBOE:VIX", "^TNX": "TVC:TNX",
    "^FTSE": "TVC:UKX", "^N225": "TVC:NI225", "^GDAXI": "XETR:DAX", "^HSI": "TVC:HSI",
    "^STOXX50E": "TVC:SX5E", "^FCHI": "EURONEXT:PX1",
}

# Yahoo suffix → TradingView exchange prefix
_SUFFIX = {
    "TO": "TSX", "V": "TSXV", "L": "LSE", "HK": "HKEX", "NS": "NSE", "BO": "BSE",
    "T": "TSE", "DE": "XETR", "F": "FWB", "PA": "EURONEXT", "AS": "EURONEXT",
    "BR": "EURONEXT", "MI": "MIL", "MC": "BME", "SW": "SIX", "AX": "ASX",
    "SI": "SGX", "KS": "KRX", "KQ": "KRX", "SS": "SSE", "SZ": "SZSE",
    "SA": "BMFBOVESPA", "MX": "BMV", "ST": "OMXSTO", "CO": "OMXCOP", "OL": "OSL",
    "HE": "OMXHEX", "TW": "TWSE", "JK": "IDX", "NZ": "NZX", "IR": "EURONEXT",
}

_CRYPTO_QUOTES = ("USD", "USDT", "EUR", "GBP", "BTC", "ETH")


def to_tradingview_symbol(yahoo: str) -> str:
    s = (yahoo or "").strip().upper()
    if not s:
        return s
    if s in _INDICES:
        return _INDICES[s]
    if s.startswith("^"):
        return s[1:]
    if s.endswith("=X"):                      # EURUSD=X, JPY=X (USD base implied)
        pair = s[:-2]
        return f"FX:{pair if len(pair) == 6 else 'USD' + pair}"
    if s.endswith("=F"):                      # ES=F, CL=F, GC=F
        return f"{s[:-2]}1!"
    if "." in s:                              # 0700.HK, RY.TO, SAP.DE
        base, suffix = s.rsplit(".", 1)
        exch = _SUFFIX.get(suffix)
        if exch:
            if exch == "HKEX":
                base = base.lstrip("0") or "0"
            return f"{exch}:{base.replace('-', '.')}"
        return s
    if "-" in s:
        base, quote = s.rsplit("-", 1)
        if quote in _CRYPTO_QUOTES and len(base) >= 2:
            return f"{base}{quote}"               # BTC-USD → BTCUSD
        return s.replace("-", ".")                # BRK-B → BRK.B
    return s
