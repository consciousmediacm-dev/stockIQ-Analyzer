"""
Shared helpers for the cache build scripts.

write_cache() is the only way the scripts write their JSON:
  • refuses to write when coverage is below min_coverage of the expected tickers
    (a rate-limited or blocked run would otherwise replace good data with a
    near-empty file and silently break the scanners)
  • refuses when the new file is much smaller than the one it replaces
  • writes atomically (temp file + rename)
  • records generated_at / count / coverage in cache/screener/manifest.json,
    which the System Status page reads
Exits the process with status 1 on refusal so CI marks the step as failed.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCREENER_DIR = Path(__file__).resolve().parent.parent / "screener"
MANIFEST = SCREENER_DIR / "manifest.json"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def update_manifest(name: str, **fields) -> None:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        manifest = {}
    manifest[name] = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
    _atomic_write(MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def check_coverage(count: int, expected: int, previous: int, min_coverage: float, max_shrink: float) -> str | None:
    """Return a refusal reason, or None when the new data is safe to write."""
    if expected and count / expected < min_coverage:
        return f"only {count}/{expected} tickers ({count / expected:.0%}) — below {min_coverage:.0%} minimum"
    if previous and count < previous * (1 - max_shrink):
        return f"{count} tickers vs {previous} in the existing file — shrank more than {max_shrink:.0%}"
    return None


def write_cache(
    path: Path,
    data: dict,
    expected: int,
    min_coverage: float = 0.9,
    max_shrink: float = 0.1,
    exit_on_refusal: bool = True,
) -> bool:
    """Validate and write a ticker-keyed cache file. See module docstring."""
    previous = 0
    if path.exists():
        try:
            previous = len(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            previous = 0

    reason = check_coverage(len(data), expected, previous, min_coverage, max_shrink)
    if reason:
        print(f"REFUSING to write {path.name}: {reason}. Existing file left untouched.")
        if exit_on_refusal:
            sys.exit(1)
        return False

    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))
    update_manifest(path.name, count=len(data), expected=expected,
                    coverage=round(len(data) / expected, 3) if expected else None)
    print(f"Saved → {path} ({len(data)}/{expected} tickers)")
    return True
