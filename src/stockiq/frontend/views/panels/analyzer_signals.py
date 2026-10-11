"""Indicator readout + Buying Pressure (BX) panels for the Stock Analyzer page."""

import pandas as pd
import streamlit as st

from stockiq.backend.services.analyzer_service import get_buying_pressure
from stockiq.frontend.theme import DN, MUT, UP


def render_indicator_readout(readout: dict) -> None:
    st.markdown("**Indicator Readout**")
    st.caption("Where price sits relative to its indicators — descriptive, not a buy/sell call.")
    icons = {"up": "▲", "down": "▼", "flat": "•"}
    colors = {"up": UP, "down": DN, "flat": MUT}
    for direction, text in readout["notes"]:
        st.markdown(
            f'<div style="font-size:0.88rem;margin:3px 0">'
            f'<span style="color:{colors[direction]};margin-right:6px">{icons[direction]}</span>{text}</div>',
            unsafe_allow_html=True,
        )


def render_buying_pressure(df: pd.DataFrame) -> None:
    st.markdown("**Buying Pressure (BX)**")
    st.caption("2/3 conditions = signal · 3/3 = strong · based on completed bars only")

    _render_bx_panel(get_buying_pressure(df, "monthly"), "Monthly")
    st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
    _render_bx_panel(get_buying_pressure(df, "weekly"), "Weekly")


# ── Private helpers ────────────────────────────────────────────────────────────

def _render_bx_panel(bx: dict, label: str) -> None:
    strength = bx["strength"]
    if bx["signal"] and strength == 3:
        badge_bg, badge_txt = "#16A34A", "BX TRIGGERED ✓✓✓"
    elif bx["signal"]:
        badge_bg, badge_txt = "#22C55E", "BX TRIGGERED ✓✓"
    else:
        badge_bg, badge_txt = "#475569", "NOT TRIGGERED"

    bar_label = bx.get("bar_label", "")
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
        f'<span style="font-weight:600">{label}</span>'
        f'<span style="background:{badge_bg};color:#fff;padding:2px 10px;'
        f'border-radius:4px;font-size:0.78rem">{badge_txt}</span>'
        f'<span style="color:{MUT};font-size:0.72rem">{bar_label}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    for cond in bx["conditions_met"]:
        st.markdown(f"&nbsp;&nbsp;✅ {cond}")
    for cond in bx["conditions_missing"]:
        st.markdown(f"&nbsp;&nbsp;❌ {cond}")
