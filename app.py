import os
import sys
from dotenv import load_dotenv
load_dotenv()

import streamlit as st

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Stock Screener & AI Analyzer",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "Free stock technical analysis: moving averages, RSI, Fibonacci retracement, "
                 "short squeeze scanner, bounce radar, and Munger quality watchlist."
    },
)


def _show_overloaded_page():
    st.markdown("""
    <style>
    .overload-wrap {
        display: flex; flex-direction: column; align-items: center;
        justify-content: center; padding: 80px 24px 40px;
        text-align: center; font-family: sans-serif;
    }
    .overload-icon { font-size: 4rem; margin-bottom: 12px; }
    .overload-title { font-size: 2rem; font-weight: 700; color: #F8FAFC; margin-bottom: 8px; }
    .overload-sub {
        font-size: 1.1rem; color: #94A3B8; max-width: 520px;
        line-height: 1.6; margin-bottom: 36px;
    }
    </style>
    <div class="overload-wrap">
        <div class="overload-icon">📈</div>
        <div class="overload-title">The app is temporarily unavailable</div>
        <div class="overload-sub">
            Something went wrong while starting up. Please try again in a few minutes.
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()


try:
    # Inject Streamlit secrets into os.environ (Streamlit Cloud only — no-op locally)
    try:
        for _key, _val in st.secrets.items():
            if isinstance(_val, str):
                os.environ[_key] = _val
    except Exception:
        pass  # no secrets.toml — running locally with .env / environment variables

    _src = os.path.join(os.path.dirname(__file__), "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)

    from stockiq.logging_setup import configure_logging
    configure_logging()

    from stockiq.frontend.layout.banner import render_top_banner
    from stockiq.frontend.layout.nav import get_pages
    from stockiq.frontend.layout.sidebar import render_sidebar
    from stockiq.frontend.views.seo import inject_seo

except Exception:
    import logging
    logging.getLogger("stockiq.app").exception("App failed to start")
    _show_overloaded_page()

# ── SEO metadata ──────────────────────────────────────────────────────────────
inject_seo()

# ── Navigation + shell ────────────────────────────────────────────────────────
pg = st.navigation(get_pages())
render_top_banner()
render_sidebar()
pg.run()
