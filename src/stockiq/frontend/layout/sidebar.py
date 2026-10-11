import streamlit as st

from stockiq.brand import SUPPORT_LABEL, SUPPORT_URL
from stockiq.frontend.layout.appearance import render_appearance_panel


def render_sidebar() -> None:
    """Sidebar content: appearance settings, optional support link (config/brand.yml), data caption."""
    render_appearance_panel()
    with st.sidebar:
        if SUPPORT_URL:
            st.link_button(SUPPORT_LABEL, SUPPORT_URL, use_container_width=True)
            st.markdown("---")
        st.caption("Market data: Yahoo Finance (Alpha Vantage fallback) · may be delayed")
