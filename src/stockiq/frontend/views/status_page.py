from datetime import datetime

import pandas as pd
import streamlit as st

from stockiq.backend.services.status_service import get_system_status

_STATE_ICON = {"ok": "🟢", "stale": "🟠", "missing": "🔴"}


def _ts(v: float | None) -> str:
    return datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M:%S") if v else "—"


def render_status_page() -> None:
    st.title("🩺 System Status")
    st.caption("Data-source health, cache freshness and recent problems for this app instance.")
    status = get_system_status()

    # ── Providers ─────────────────────────────────────────────────────────────
    st.subheader("Market data providers")
    st.caption("Counts since this app process started. Order = failover order (config/app.yml → history.providers).")
    rows = []
    for name, s in status["providers"].items():
        if not s.get("configured", True):
            health = "⚪ not configured"
        elif s["last_error_at"] and (not s["last_success"] or s["last_error_at"] > s["last_success"]):
            health = "🔴 failing"
        elif s["last_success"]:
            health = "🟢 ok"
        else:
            health = "⚪ not used yet"
        rows.append({
            "provider": name, "health": health, "requests": s["calls"],
            "tickers served": s["tickers_served"], "failures": s["failures"],
            "last success": _ts(s["last_success"]), "last error": (s["last_error"] or "—")[:160],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    issues = [i for s in status["providers"].values() for i in s.get("issues", [])]
    if issues:
        with st.expander(f"Data-quality notes ({len(issues)})"):
            st.markdown("\n".join(f"- {i}" for i in issues))

    # ── Caches ────────────────────────────────────────────────────────────────
    st.subheader("Pre-built screener data")
    caches = pd.DataFrame(status["caches"])
    caches.insert(0, " ", caches.pop("state").map(_STATE_ICON))
    caches["age_days"] = [
        "—" if a is None else (f"~{a}" if approx else str(a))
        for a, approx in zip(caches["age_days"], caches.pop("approx"))
    ]
    st.dataframe(caches, hide_index=True, width="stretch")
    st.caption("Ages marked ~ come from file timestamps (no build manifest yet) and may reflect deploy time.")

    # ── Keys ──────────────────────────────────────────────────────────────────
    st.subheader("API keys")
    keys = pd.DataFrame(status["keys"])
    keys["set"] = keys["set"].map({True: "✅", False: "—"})
    st.dataframe(keys, hide_index=True, width="stretch")

    # ── Problems ──────────────────────────────────────────────────────────────
    st.subheader("Recent warnings & errors")
    if status["problems"]:
        st.dataframe(pd.DataFrame(status["problems"]), hide_index=True, width="stretch")
    else:
        st.success("No warnings or errors logged since this app process started.")

    st.caption(f"{status['registered_caches']} cached data functions registered.")


render_status_page()
