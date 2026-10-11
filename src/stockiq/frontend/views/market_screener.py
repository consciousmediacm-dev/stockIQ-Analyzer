import streamlit as st

from stockiq.backend.models.signals import CANDLE_SIGNALS
from stockiq.backend.services.market_screener_service import (
    PRESETS,
    filters_from_preset,
    get_market_snapshot,
    screen_market,
)

_LABELS = ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]
_SORTS = {
    "20-day $ volume": "dollar_vol_20", "Signal score": "score", "RSI": "rsi",
    "1-day %": "chg_1d_pct", "1-week %": "ret_1w_pct", "1-month %": "ret_1m_pct",
    "3-month %": "ret_3m_pct", "1-year %": "ret_1y_pct", "Distance from MA200 %": "dist_ma200_pct",
    "Bounce score": "bounce_score", "% from 52-week high": "pct_from_52w_high", "Price": "close",
}
_COLUMNS = {
    "symbol": "Symbol", "name": "Name", "is_etf": "ETF", "exchange": "Exchange", "close": "Price",
    "chg_1d_pct": "1D %", "ret_1m_pct": "1M %", "ret_1y_pct": "1Y %", "rsi": "RSI",
    "dist_ma200_pct": "vs MA200 %", "label": "Signal", "score": "Score", "candle_signal": "Candles",
    "bounce_score": "Bounce", "pct_from_52w_high": "From 52W high %", "dollar_vol_20": "Avg $ vol (20d)",
    "link": "Analyze",
}


def render_market_screener() -> None:
    st.title("🗺️ Market Screener")
    st.caption("Every active US-listed stock and ETF, refreshed nightly after the close. "
               "Same indicators and scoring as the Stock Analyzer.")

    snap = get_market_snapshot()
    df = snap["df"]
    if df.empty:
        st.info(
            "The full-market snapshot hasn't been built yet. It is produced nightly by the "
            "**Market Snapshot** GitHub Action (or run `python cache/scripts/build_market_snapshot.py "
            "--out cache/market/market_snapshot.parquet` locally)."
        )
        return

    n_etf = int(df["is_etf"].sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("Symbols covered", f"{len(df):,}")
    m2.metric("Stocks / ETFs", f"{len(df) - n_etf:,} / {n_etf:,}")
    m3.metric("Data as of", snap["as_of"])

    # ── Filters ───────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([2, 1, 1])
    preset = c1.selectbox("Preset", list(PRESETS))
    asset = c2.selectbox("Type", ["all", "stocks", "etfs"], format_func=str.title)
    query = c3.text_input("Symbol / name contains", "")

    with st.expander("More filters", expanded=False):
        f1, f2, f3 = st.columns(3)
        min_price = f1.number_input("Min price ($)", 0.0, value=0.0, step=1.0)
        min_dvol = f2.select_slider(
            "Min avg daily $ volume", options=[0, 100_000, 1_000_000, 10_000_000, 100_000_000],
            value=0, format_func=lambda v: "Any" if v == 0 else f"${v:,.0f}",
            help="Filters out thinly traded symbols — many small ETFs trade under $1M a day.",
        )
        exchanges = f3.multiselect("Exchange", sorted(df["exchange"].dropna().unique()))
        g1, g2, g3 = st.columns(3)
        rsi_rng = g1.slider("RSI range", 0, 100, (0, 100))
        labels = g2.multiselect("Signal score", _LABELS)
        candles = g3.multiselect("Candle signal", [lbl for lbl, _ in CANDLE_SIGNALS])
        h1, h2, h3 = st.columns(3)
        sort_label = h1.selectbox("Sort by", ["Preset default"] + list(_SORTS))
        ascending = h2.toggle("Ascending", value=False)
        top_n = h3.number_input("Max rows", 10, 5000, 200, step=50)

    filters, extra = filters_from_preset(
        preset,
        asset_type=asset, query=query or None, min_price=min_price or None,
        min_dollar_vol=min_dvol or None, exchanges=exchanges or None,
        rsi_min=rsi_rng[0] if rsi_rng[0] > 0 else None, rsi_max=rsi_rng[1] if rsi_rng[1] < 100 else None,
        labels=labels or None, candle_signals=candles or None, top_n=int(top_n),
    )
    if sort_label != "Preset default":
        filters.sort_by, filters.ascending = _SORTS[sort_label], ascending
        extra.pop("abs_sort", None)

    result = screen_market(df, filters, **extra)
    st.caption(f"{len(result):,} shown")
    if result.empty:
        st.warning("No symbols match these filters.")
        return

    table = result.copy()
    table["link"] = "/analyzer?tic=" + table["symbol"]
    st.dataframe(
        table[list(_COLUMNS)].rename(columns=_COLUMNS),
        hide_index=True, width="stretch", height=640,
        column_config={
            "Analyze": st.column_config.LinkColumn("Analyze", display_text="Open →"),
            "Avg $ vol (20d)": st.column_config.NumberColumn(format="$%,.0f"),
            "Price": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    st.download_button("⬇ Download CSV", result.to_csv(index=False), "market_screen.csv", "text/csv")


render_market_screener()
