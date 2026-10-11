import streamlit as st

from stockiq.backend.config import SPX_TICKERS
from stockiq.backend.services.backtest_service import run_signal_backtest

_PRESETS = {
    "Top 25 S&P 500": SPX_TICKERS[:25],
    "Top 100 S&P 500": SPX_TICKERS[:100],
    "Full S&P universe": SPX_TICKERS,
}


def _highlight_baseline(df):
    return df.style.apply(
        lambda r: ["font-weight:700; background-color: rgba(148,163,184,0.15)"] * len(r)
        if r.name == "ALL (baseline)" else [""] * len(r),
        axis=1,
    )


def render_backtest_page() -> None:
    st.title("🧪 Signal Backtest")
    st.markdown(
        "Replays the **Stock Analyzer signal score** and the **price-only scanners** "
        "(Candle Screener, MA200 Bounce Radar, RSI zones) over history and measures what "
        "happened next. Compare every row to **ALL (baseline)** — a signal is only useful "
        "if it beats doing nothing."
    )

    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
    preset = c1.selectbox("Universe", list(_PRESETS) + ["Custom"])
    years = c2.slider("Years", 3, 20, 10)
    horizon = c3.selectbox("Horizon (days)", [5, 20, 60], index=1)
    step = c4.selectbox("Sample every", [1, 5, 20, 60], index=1,
                        help="Use ≥ horizon for non-overlapping samples (honest t-stats)")

    if preset == "Custom":
        raw = st.text_input("Tickers (comma-separated)", "AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM, XOM")
        tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
    else:
        tickers = _PRESETS[preset]

    if not st.button("▶ Run backtest", type="primary"):
        st.info("Larger universes download a lot of history the first time (cached for 6 h afterwards).")
        return

    with st.spinner(f"Backtesting {len(tickers)} tickers over {years} years…"):
        result = run_signal_backtest(tickers, years=years, step=step)

    if result.get("missing"):
        st.warning(f"No data for: {', '.join(result['missing'][:30])}")
    if not result["tables"]:
        st.error("No scorable history. The data source may be unavailable, or the window is too short "
                 "(the 200-week MA needs ~4 years of warm-up).")
        return

    meta = result["meta"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Tickers", meta["tickers"])
    m2.metric("Samples", f"{meta['rows']:,}")
    m3.metric("Window", f"{meta['start']} → {meta['end']}")

    with st.expander("⚠️ Caveats — read before trusting these numbers"):
        from stockiq.backend.backtest.report import CAVEATS, HOW_TO_READ
        st.markdown(CAVEATS + "\n\n" + HOW_TO_READ)

    for title, table in result["tables"].items():
        cols = ["n", "tickers"] + [c for c in table.columns if c.endswith(f"_{horizon}d")]
        st.subheader(title)
        st.dataframe(_highlight_baseline(table[cols]), width="stretch")

    reg = result["regression"].get(horizon)
    if reg is not None and not reg.empty:
        st.subheader(f"Component regression · {horizon}-day excess return")
        st.caption("% excess return per +1 point of each score component. Near-zero or negative "
                   "coefficients flag components whose current weight isn't earned.")
        st.dataframe(reg, width="stretch")

    st.download_button("⬇ Download full report (Markdown)", result["markdown"],
                       file_name="stockiq_backtest.md")


render_backtest_page()
