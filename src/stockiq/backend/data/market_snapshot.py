"""
Load the nightly full-market snapshot (see backend/market/snapshot.py).

Lookup order:
  1. cache/market/market_snapshot.parquet in the repo (local dev / Docker builds)
  2. $STOCKIQ_DATA_DIR/market_snapshot.parquet, unless the published build is newer
     (checked via the small market_snapshot.json next to the asset, at most every
     30 min) — or, when that check fails, unless it is older than refresh_hours
  3. download from MARKET_SNAPSHOT_URL (GitHub Release asset), saved to (2)
  4. a stale copy from (2) if the download fails — better old data than none
Returns an empty DataFrame when nothing is available (e.g. before the first
nightly run); callers show a "not built yet" message.
"""

import json
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
LOCAL_META = DATA_DIR / "market_snapshot.local.json"     # {"generated_at": ...} of the local copy


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
    """Read a snapshot and align it to the current schema (older files may have
    extra or missing columns until the next nightly build)."""
    from stockiq.backend.market.snapshot import SNAPSHOT_COLUMNS
    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return pd.DataFrame()
    return df.reindex(columns=SNAPSHOT_COLUMNS)


def _remote_generated_at() -> str | None:
    """Build time of the published snapshot (from its small .json sidecar), or None."""
    if not MARKET_SNAPSHOT_URL:
        return None
    try:
        resp = requests.get(MARKET_SNAPSHOT_URL.rsplit(".", 1)[0] + ".json", timeout=15,
                            headers={"User-Agent": "stockiq-app"})
        resp.raise_for_status()
        return resp.json().get("generated_at") or None
    except (requests.RequestException, ValueError) as exc:
        logger.info("Snapshot version check failed: %s", exc)
        return None


def _local_generated_at() -> str | None:
    try:
        return json.loads(LOCAL_META.read_text()).get("generated_at")
    except Exception:
        return None


def _needs_download(remote: str | None) -> bool:
    if not LOCAL_FILE.exists():
        return True
    if remote:
        return remote != _local_generated_at()
    return (time.time() - LOCAL_FILE.stat().st_mtime) >= MARKET_SNAPSHOT_REFRESH_HOURS * 3600


@ttl_cache(1800)
def load_market_snapshot() -> pd.DataFrame:
    if REPO_FILE.exists():
        return _read(REPO_FILE)
    remote = _remote_generated_at()
    if MARKET_SNAPSHOT_URL and _needs_download(remote):
        if _download(MARKET_SNAPSHOT_URL, LOCAL_FILE):
            try:
                LOCAL_META.parent.mkdir(parents=True, exist_ok=True)
                LOCAL_META.write_text(json.dumps({"generated_at": remote}))
            except OSError as exc:
                logger.warning("Could not record snapshot version: %s", exc)
    return _read(LOCAL_FILE) if LOCAL_FILE.exists() else pd.DataFrame()
