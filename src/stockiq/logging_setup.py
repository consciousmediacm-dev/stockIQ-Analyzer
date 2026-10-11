"""
One place to configure logging for the app.

  STOCKIQ_LOG_LEVEL   DEBUG | INFO (default) | WARNING | ERROR

configure_logging() is idempotent (Streamlit re-runs app.py on every
interaction). Warnings and errors are also kept in an in-memory ring buffer so
the System Status page can show what went wrong recently without shell access.
"""

import logging
import os
import threading
from collections import deque
from datetime import datetime

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False
_lock = threading.Lock()


class RingBufferHandler(logging.Handler):
    """Keeps the last `capacity` records at WARNING or above."""

    def __init__(self, capacity: int = 200) -> None:
        super().__init__(level=logging.WARNING)
        self.records: deque[dict] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append({
                "time":    datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level":   record.levelname,
                "logger":  record.name,
                "message": record.getMessage()[:500],
            })
        except Exception:  # a logging handler must never raise
            self.handleError(record)


RECENT = RingBufferHandler()


def configure_logging() -> None:
    global _configured
    with _lock:
        if _configured:
            return
        level = getattr(logging, os.environ.get("STOCKIQ_LOG_LEVEL", "INFO").upper(), logging.INFO)
        logging.basicConfig(level=level, format=_FORMAT)
        root = logging.getLogger()
        root.setLevel(level)
        root.addHandler(RECENT)
        # Third-party chatter
        for noisy in ("yfinance", "urllib3", "peewee", "httpx", "watchdog"):
            logging.getLogger(noisy).setLevel(logging.WARNING if level <= logging.INFO else level)
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        _configured = True


def recent_problems(limit: int = 50) -> list[dict]:
    """Most recent warnings/errors, newest first."""
    return list(RECENT.records)[-limit:][::-1]
