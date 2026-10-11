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
from datetime import date, timedelta

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

# ── Circuit breaker ───────────────────────────────────────────────────────────
# yfinance doesn't raise when Yahoo is unreachable — it fails each ticker in turn
# (~0.3 s apiece), so a 300-ticker scan would hang ~90 s per page view during an
# outage. Providers that set `probe_symbol` are probed with one cheap request
# before large batches; a failed probe or an all-empty batch marks the provider
# down for BREAKER_SECONDS and requests go straight to the next provider.
BREAKER_SECONDS = 60
PROBE_THRESHOLD = 20      # batches larger than this are probed first
_down_until: dict[str, float] = {}


def _is_down(name: str) -> bool:
    return _down_until.get(name, 0.0) > time.time()


def _trip(name: str, reason: str) -> None:
    _down_until[name] = time.time() + BREAKER_SECONDS
    logger.warning("%s marked down for %ds: %s", name, BREAKER_SECONDS, reason)
    _record(name, error=f"circuit open: {reason}")


def _probe_ok(provider: HistoryProvider) -> bool:
    symbol = getattr(provider, "probe_symbol", None)
    if not symbol:
        return True
    try:
        return bool(provider.daily_history([symbol], date.today() - timedelta(days=10), date.today()))
    except ProviderError:
        return False


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
    for name, until in _down_until.items():
        if until > time.time() and name in out:
            out[name]["down_until"] = until
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
        if not provider.is_configured() or _is_down(name):
            continue
        if len(remaining) > PROBE_THRESHOLD and not _probe_ok(provider):
            _trip(name, f"probe {getattr(provider, 'probe_symbol', '')} returned no data")
            continue
        try:
            got = with_retry(
                lambda: provider.daily_history(remaining, start, end),
                attempts=2, label=f"{name} history",
            )
        except ProviderError as exc:
            logger.warning("%s history failed for %d tickers: %s", name, len(remaining), exc)
            _record(name, error=str(exc))
            if not isinstance(exc, RateLimitError):
                _trip(name, str(exc)[:120])
            continue
        if not got and len(remaining) >= 5:
            _trip(name, f"returned nothing for {len(remaining)} tickers")
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
