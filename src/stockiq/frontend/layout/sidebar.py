import streamlit as st

from stockiq.brand import SUPPORT_LABEL, SUPPORT_URL


def render_sidebar() -> None:
    """Sidebar content: optional support link (config/brand.yml) and data caption."""
    with st.sidebar:
        if SUPPORT_URL:
            st.link_button(SUPPORT_LABEL, SUPPORT_URL, use_container_width=True)
            st.markdown("---")
        st.caption("Market data: Yahoo Finance (Alpha Vantage fallback) · may be delayed")
