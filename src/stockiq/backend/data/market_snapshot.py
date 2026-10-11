"""
Load the nightly full-market snapshot (see backend/market/snapshot.py).

Lookup order:
  1. cache/market/market_snapshot.parquet in the repo (local dev / Docker builds)
  2. $STOCKIQ_DATA_DIR/market_snapshot.parquet if downloaded < refresh_hours ago
  3. download from MARKET_SNAPSHOT_URL (GitHub Release asset), saved to (2)
  4. a stale copy from (2) if the download fails — better old data than none
Returns an empty DataFrame when nothing is available (e.g. before the first
nightly run); callers show a "not built yet" message.
"""

import logging
import os
import time
from pathlib import Path

import pandas as pd
import requests

from stockiq.backend.cache import DATA_DIR, ttl_cache
from stockiq.backend.config import MARKET_SNAPSHOT_REFRESH_HOURS, MARKET_SNAPSHOT_URL

logger = logging.getLogger(__name__)

REPO_FILE = Path(__file__).resolve().parents[4] / "cache" / "market" / "market_snapshot.parquet"
LOCAL_FILE = DATA_DIR / "market_snapshot.parquet"


def _download(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, timeout=60, headers={"User-Agent": "stockiq-app"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Market snapshot download failed: %s", exc)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(resp.content)
    os.replace(tmp, dest)
    logger.info("Downloaded market snapshot (%d KB)", len(resp.content) // 1024)
    return True


def _read(path: Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return pd.DataFrame()


@ttl_cache(1800)
def load_market_snapshot() -> pd.DataFrame:
    if REPO_FILE.exists():
        return _read(REPO_FILE)
    fresh = LOCAL_FILE.exists() and (time.time() - LOCAL_FILE.stat().st_mtime) < MARKET_SNAPSHOT_REFRESH_HOURS * 3600
    if not fresh and MARKET_SNAPSHOT_URL:
        _download(MARKET_SNAPSHOT_URL, LOCAL_FILE)
    return _read(LOCAL_FILE) if LOCAL_FILE.exists() else pd.DataFrame()
