"""Brand settings from config/brand.yml — one place to rename / re-skin the app."""

from pathlib import Path

import yaml

_cfg: dict = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "brand.yml").read_text()) or {}

APP_NAME: str      = _cfg.get("app_name") or "Stock Analyzer"
TAGLINE: str       = _cfg.get("tagline") or ""
SITE_URL: str      = (_cfg.get("site_url") or "").rstrip("/")
LOGO_URL: str      = _cfg.get("logo_url") or ""
SUPPORT_URL: str   = _cfg.get("support_url") or ""
SUPPORT_LABEL: str = _cfg.get("support_label") or "Support this project"


def brand(text: str) -> str:
    """Replace the upstream product name in shared copy with the configured app name."""
    return text.replace("StockIQ", APP_NAME)
