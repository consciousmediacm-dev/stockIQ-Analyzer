import streamlit as st

from stockiq.brand import APP_NAME, LOGO_URL


def render_top_banner() -> None:
    """Fixed top bar with the configured brand (config/brand.yml) and a nav-hide rule for utility pages."""
    logo = f'<img src="{LOGO_URL}" alt="" style="height:24px;vertical-align:middle;margin-right:8px;">' if LOGO_URL else ""
    st.markdown(
        f"""
<div style="
    position: fixed; top: 0; left: 0; width: 100%; z-index: 9999;
    background: #0F172A; padding: 10px 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4); font-family: sans-serif;
">
    <span style="font-size: 1.2rem; font-weight: 700; color: #F8FAFC; letter-spacing: 0.5px;">
        {logo}{APP_NAME}
    </span>
</div>
<div style="margin-top: 48px;"></div>
""",
        unsafe_allow_html=True,
    )

    # Hide the spy-gaps shareable embed page from the sidebar nav.
    st.markdown(
        """
<style>
[data-testid="stSidebarNav"] a[href$="/spy-gaps"],
[data-testid="stSidebarNavLink"] a[href$="/spy-gaps"] { display: none !important; }
</style>
""",
        unsafe_allow_html=True,
    )
