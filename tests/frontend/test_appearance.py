"""Sidebar appearance settings: validation (cookie values are untrusted) and CSS."""

import pytest
from streamlit.testing.v1 import AppTest

from stockiq.frontend.layout.appearance import DEFAULTS, PRESETS, build_css, readable_on, sanitize


def test_sanitize_defaults_and_valid_values():
    assert sanitize(None) == DEFAULTS
    s = sanitize({"mode": "light", "bg": "#fafafa", "accent": "#123abc", "font_px": "18"})
    assert s == {"mode": "light", "bg": "#FAFAFA", "accent": "#123ABC", "font_px": 18}


@pytest.mark.parametrize("bad", [
    {"bg": "red;} body{display:none"},
    {"accent": "#12345"},
    {"accent": "</style><script>alert(1)</script>"},
    {"font_px": 99},
    {"font_px": "x"},
    {"mode": "neon"},
])
def test_sanitize_rejects_untrusted_values(bad):
    s = sanitize(bad)
    css = build_css(s)
    assert "<" not in css and "display:none" not in css
    assert 12 <= s["font_px"] <= 22 and s["mode"] in PRESETS


def test_light_mode_switches_background_preset():
    assert sanitize({"mode": "light"})["bg"] == PRESETS["light"]["bg"]


def test_text_contrast_follows_background():
    assert readable_on("#FFFFFF") == PRESETS["light"]["text"]
    assert readable_on("#0F172A") == PRESETS["dark"]["text"]
    css = build_css(sanitize({"mode": "dark", "bg": "#FFFF00", "font_px": 20}))
    assert "font-size: 20px" in css and "background-color: #FFFF00" in css
    assert f"color: {PRESETS['light']['text']}" in css         # dark text on a yellow page


APP = """
import streamlit as st
from stockiq.frontend.layout.appearance import render_appearance_panel
render_appearance_panel()
st.button("Primary", type="primary")
"""


def test_panel_applies_css_and_resets():
    at = AppTest.from_string(APP, default_timeout=30).run()
    assert not at.exception
    assert at.session_state.appearance == DEFAULTS

    at.sidebar.toggle(key="appearance_light").set_value(True).run()
    assert at.session_state.appearance["mode"] == "light"
    assert at.session_state.appearance["bg"] == PRESETS["light"]["bg"]

    at.sidebar.slider(key="appearance_font").set_value(19).run()
    assert at.session_state.appearance["font_px"] == 19
    assert at.session_state.appearance_saved["font_px"] == 19          # cookie write issued

    at.sidebar.button[0].click().run()                                  # Reset to default
    assert at.session_state.appearance == DEFAULTS
    assert not at.exception
