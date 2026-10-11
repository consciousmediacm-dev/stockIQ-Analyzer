"""
Market-data provider layer.

    from stockiq.backend.data.providers import get_daily_history
    prices = get_daily_history(["AAPL", "MSFT"], start, end)

Providers are tried in the order set by `history.providers` in
backend/config/app.yml. Tickers that the first provider can't serve (missing,
empty or failing validation) are retried on the next one, so a partial outage
degrades coverage instead of blanking a whole scan.

Every call records per-provider status (last success, last error, counts) for
the health page — see provider_status().
"""

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date

import pandas as pd

from stockiq.backend.config import HISTORY_PROVIDERS
from stockiq.backend.data.providers.alphavantage import AlphaVantageProvider
from stockiq.backend.data.providers.base import (
    HistoryProvider,
    ProviderError,
    ProviderNotConfigured,
    RateLimitError,
    with_retry,
)
from stockiq.backend.data.providers.validation import ValidationResult, validate_ohlcv
from stockiq.backend.data.providers.yahoo import YahooProvider

logger = logging.getLogger(__name__)

__all__ = [
    "HistoryProvider", "ProviderError", "ProviderNotConfigured", "RateLimitError",
    "ValidationResult", "get_daily_history", "get_provider", "provider_status",
    "validate_ohlcv", "with_retry",
]

_FACTORIES = {
    "yahoo": YahooProvider,
    "alphavantage": AlphaVantageProvider,
}
_instances: dict[str, HistoryProvider] = {}


@dataclass
class _Status:
    calls: int = 0
    tickers_served: int = 0
    failures: int = 0
    last_success: float | None = None
    last_error: str | None = None
    last_error_at: float | None = None
    issues: list[str] = field(default_factory=list)


_status: dict[str, _Status] = {}
_status_lock = threading.Lock()


def get_provider(name: str) -> HistoryProvider:
    if name not in _instances:
        _instances[name] = _FACTORIES[name]()
    return _instances[name]


def _record(name: str, served: int = 0, error: str | None = None, issues: list[str] | None = None) -> None:
    with _status_lock:
        s = _status.setdefault(name, _Status())
        s.calls += 1
        s.tickers_served += served
        if served:
            s.last_success = time.time()
        if error:
            s.failures += 1
            s.last_error, s.last_error_at = error, time.time()
        if issues:
            s.issues = (issues + s.issues)[:20]


def provider_status() -> dict[str, dict]:
    """Snapshot of per-provider health for the status page."""
    with _status_lock:
        out = {name: asdict(s) for name, s in _status.items()}
    for name in HISTORY_PROVIDERS:
        if name in _FACTORIES:
            out.setdefault(name, asdict(_Status()))
            out[name]["configured"] = get_provider(name).is_configured()
    return out


def get_daily_history(
    tickers: list[str],
    start: date,
    end: date | None = None,
    providers: list[str] | None = None,
    min_rows: int = 1,
) -> dict[str, pd.DataFrame]:
    """
    Daily adjusted OHLCV for each ticker (start..end inclusive) with failover.
    Returns {ticker: DataFrame}; tickers no provider could serve are absent.
    """
    end = end or date.today()
    remaining = list(dict.fromkeys(tickers))
    out: dict[str, pd.DataFrame] = {}

    for name in providers or HISTORY_PROVIDERS:
        if not remaining:
            break
        if name not in _FACTORIES:
            logger.warning("Unknown history provider %r in config", name)
            continue
        provider = get_provider(name)
        if not provider.is_configured():
            continue
        try:
            got = with_retry(
                lambda: provider.daily_history(remaining, start, end),
                attempts=2, label=f"{name} history",
            )
        except ProviderError as exc:
            logger.warning("%s history failed for %d tickers: %s", name, len(remaining), exc)
            _record(name, error=str(exc))
            continue

        issues: list[str] = []
        for t, df in got.items():
            res = validate_ohlcv(df, t, min_rows=min_rows)
            issues.extend(res.issues)
            if res.usable:
                out[t] = res.df
        served = [t for t in remaining if t in out]
        _record(name, served=len(served), issues=issues)
        if issues:
            logger.info("%s data issues: %s", name, "; ".join(issues[:5]))
        remaining = [t for t in remaining if t not in out]

    if remaining:
        logger.warning("No provider returned data for %d tickers: %s", len(remaining), remaining[:10])
    return out
