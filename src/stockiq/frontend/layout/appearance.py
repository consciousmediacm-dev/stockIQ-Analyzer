"""
Sidebar "Appearance" panel: dark/light mode, background colour, button colour
and font size for the app frame (page, sidebar, text, inputs, buttons).
Cards and charts keep their own colours.

Choices are kept per visitor in a browser cookie (no server storage) and read
back through st.context.cookies on the next visit. Cookie values are untrusted
input that ends up inside a <style> block, so everything is validated:
colours must be #RRGGBB, mode dark|light, font size an int in range.
"""

import json
import re
from urllib.parse import quote, unquote

import streamlit as st
import streamlit.components.v1 as components

COOKIE = "stockiq_appearance"
FONT_MIN, FONT_MAX = 12, 22

PRESETS = {
    "dark":  {"bg": "#0F172A", "panel": "#1E293B", "text": "#F1F5F9", "muted": "#94A3B8", "border": "#334155"},
    "light": {"bg": "#FFFFFF", "panel": "#F1F5F9", "text": "#0F172A", "muted": "#475569", "border": "#CBD5E1"},
}
DEFAULTS = {"mode": "dark", "bg": PRESETS["dark"]["bg"], "accent": "#22C55E", "font_px": 16}

# Always applied: metric numbers show in full (shrink to fit) instead of being cut off with "…".
BASE_CSS = """
[data-testid="stMetricValue"] { font-size: clamp(1.1rem, 2vw, 2.25rem); }
[data-testid="stMetricValue"] > div { overflow: visible; text-overflow: clip; white-space: nowrap; }
"""

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def sanitize(raw: dict | None) -> dict:
    """Return a complete, safe settings dict; anything invalid falls back to the default."""
    raw = raw if isinstance(raw, dict) else {}
    mode = raw.get("mode") if raw.get("mode") in PRESETS else DEFAULTS["mode"]
    out = {"mode": mode, "bg": PRESETS[mode]["bg"], "accent": DEFAULTS["accent"], "font_px": DEFAULTS["font_px"]}
    for key in ("bg", "accent"):
        val = raw.get(key)
        if isinstance(val, str) and _HEX.match(val):
            out[key] = val.upper()
    try:
        font = int(raw.get("font_px", out["font_px"]))
        if FONT_MIN <= font <= FONT_MAX:
            out["font_px"] = font
    except (TypeError, ValueError):
        pass
    return out


def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def readable_on(hex_color: str) -> str:
    """Near-black or near-white, whichever reads better on `hex_color`."""
    return PRESETS["light"]["text"] if _luminance(hex_color) > 0.35 else PRESETS["dark"]["text"]


def build_css(s: dict) -> str:
    """CSS for the app frame. `s` must come from sanitize()."""
    p = PRESETS[s["mode"]]
    text = readable_on(s["bg"])
    on_accent = readable_on(s["accent"])
    return f"""
html {{ font-size: {s['font_px']}px; }}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
  background-color: {s['bg']}; color: {text};
}}
[data-testid="stSidebar"], [data-testid="stSidebar"] > div {{ background-color: {p['panel']}; }}
[data-testid="stSidebar"] * {{ color: {p['text']}; }}
.stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stMarkdownContainer"] p,
.stApp [data-testid="stMarkdownContainer"] li, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp [data-testid="stWidgetLabel"], .stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricLabel"] {{ color: {text}; }}
.stApp [data-testid="stCaptionContainer"] {{ opacity: 0.8; }}
.stApp [data-baseweb="input"], .stApp [data-baseweb="input"] input, .stApp [data-baseweb="select"] > div,
.stApp [data-baseweb="textarea"], .stApp textarea, .stApp [data-testid="stNumberInputContainer"] {{
  background-color: {p['panel']}; color: {p['text']}; border-color: {p['border']};
}}
.stApp [data-testid="stExpander"] details {{ background-color: {p['panel']}; border-color: {p['border']}; }}
.stApp [data-testid="stExpander"] summary {{ background-color: transparent; color: {p['text']}; }}
.stApp [data-testid="stBaseButton-secondary"] {{
  background-color: {s['bg']}; color: {text}; border-color: {p['border']};
}}
.stApp [data-testid="stBaseButton-secondary"] [data-testid="stMarkdownContainer"] p {{ color: inherit; }}
.stApp [data-testid="stBaseButton-primary"], .stApp [data-testid="stBaseButton-primaryFormSubmit"] {{
  background-color: {s['accent']}; border-color: {s['accent']}; color: {on_accent};
}}
.stApp [data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"] p,
.stApp [data-testid="stBaseButton-primaryFormSubmit"] [data-testid="stMarkdownContainer"] p {{ color: {on_accent}; }}
.stApp [data-testid="stBaseButton-secondary"]:hover, .stApp [data-testid="stBaseButton-secondary"]:focus,
.stApp [data-testid="stBaseButton-pills"]:hover {{ border-color: {s['accent']}; color: {s['accent']}; }}
.stApp [data-testid="stBaseButton-pillsActive"] {{ background-color: {s['accent']}; border-color: {s['accent']}; color: {on_accent}; }}
.stApp [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type {{ background-color: {s['accent']} !important; }}
.stApp [data-testid="stSlider"] [data-orientation="horizontal"] > div[style*="absolute"] {{ background-color: {s['accent']} !important; }}
.stApp [data-testid="stSlider"] [data-orientation="horizontal"][style*="relative"] > div:first-child {{ background: {p['border']} !important; }}
.stApp [data-testid="stSliderThumbValue"] p {{ color: {s['accent']}; }}
.stApp a {{ color: {s['accent']}; }}
"""


def searchbox_style() -> dict | None:
    """style_overrides for streamlit-searchbox so the type-ahead box follows the chosen frame colours."""
    s = st.session_state.get("appearance") or DEFAULTS
    if s == DEFAULTS:
        return None
    p = PRESETS[s["mode"]]
    box = {"backgroundColor": p["panel"], "color": p["text"]}
    return {
        "wrapper": {"backgroundColor": s["bg"], "minHeight": "100vh"},
        "searchbox": {
            "control": {**box, "borderColor": p["border"]},
            "menuList": box,
            "singleValue": {"color": p["text"]},
            "input": {"color": p["text"]},
            "placeholder": {"color": p["muted"]},
            "option": {"color": p["text"], "backgroundColor": p["panel"], "highlightColor": p["border"]},
        },
        "dropdown": {"fill": p["text"]},
    }


def _load() -> dict:
    """Settings for this session: session_state, else the browser cookie, else defaults."""
    if "appearance" not in st.session_state:
        raw = None
        try:
            cookie = st.context.cookies.get(COOKIE)
            if cookie:
                raw = json.loads(unquote(cookie))
        except Exception:
            raw = None
        st.session_state.appearance = sanitize(raw)
        st.session_state.appearance_saved = dict(st.session_state.appearance)
    return st.session_state.appearance


def _save_cookie(s: dict) -> None:
    """Write the cookie from a zero-height component (same-origin iframe → parent document)."""
    value = quote(json.dumps(s, separators=(",", ":")))
    components.html(
        f"<script>window.parent.document.cookie = "
        f"'{COOKIE}={value}; path=/; max-age=31536000; SameSite=Lax';</script>",
        height=0,
    )


def _on_mode_change() -> None:
    mode = "light" if st.session_state.appearance_light else "dark"
    st.session_state.appearance_bg = PRESETS[mode]["bg"]       # switching mode resets the background


def _reset() -> None:
    for k in ("appearance_light", "appearance_bg", "appearance_accent", "appearance_font"):
        st.session_state.pop(k, None)
    st.session_state.appearance = dict(DEFAULTS)


def render_appearance_panel() -> None:
    """Sidebar controls, then apply the CSS and persist any change."""
    s = _load()
    for key, val in (("appearance_light", s["mode"] == "light"), ("appearance_bg", s["bg"]),
                     ("appearance_accent", s["accent"]), ("appearance_font", s["font_px"])):
        st.session_state.setdefault(key, val)

    with st.sidebar:
        with st.expander("🎨 Appearance", expanded=False):
            st.toggle("Light mode", key="appearance_light", on_change=_on_mode_change)
            c1, c2 = st.columns(2)
            c1.color_picker("Background", key="appearance_bg")
            c2.color_picker("Buttons", key="appearance_accent")
            st.slider("Font size", FONT_MIN, FONT_MAX, key="appearance_font", format="%dpx")
            st.button("Reset to default", on_click=_reset, use_container_width=True)
            st.caption("Saved in this browser. Cards and charts keep their own colours.")

        s = sanitize({
            "mode": "light" if st.session_state.appearance_light else "dark",
            "bg": st.session_state.appearance_bg,
            "accent": st.session_state.appearance_accent,
            "font_px": st.session_state.appearance_font,
        })
        st.session_state.appearance = s
        st.html(f"<style>{BASE_CSS}{build_css(s) if s != DEFAULTS else ''}</style>")
        if s != st.session_state.get("appearance_saved"):
            _save_cookie(s)
            st.session_state.appearance_saved = dict(s)
