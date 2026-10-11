"""Provider interface shared by every market-data source."""

import logging
import time
from datetime import date
from typing import Callable, Protocol, TypeVar, runtime_checkable

import pandas as pd

logger = logging.getLogger(__name__)

OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

T = TypeVar("T")


class ProviderError(Exception):
    """Raised by a provider for a failure worth retrying or failing over (network, 5xx)."""


class RateLimitError(ProviderError):
    """Provider refused the request because of a quota / rate limit."""


class ProviderNotConfigured(ProviderError):
    """Provider is missing an API key or other required setting."""


@runtime_checkable
class HistoryProvider(Protocol):
    """Daily adjusted OHLCV history."""

    name: str

    def is_configured(self) -> bool:
        """True when the provider has everything it needs (e.g. an API key)."""
        ...

    def daily_history(self, tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        """
        Split/dividend-adjusted daily bars for each ticker, start..end inclusive.
        Columns: Open, High, Low, Close, Volume; tz-naive DatetimeIndex ascending.
        Tickers with no data are simply absent from the result.
        Raise ProviderError for whole-request failures.
        """
        ...


def with_retry(
    fn: Callable[[], T],
    attempts: int = 3,
    base_delay: float = 1.0,
    retry_on: tuple[type[BaseException], ...] = (ProviderError,),
    label: str = "",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call fn, retrying with exponential backoff (1s, 2s, 4s…) on retry_on exceptions."""
    for i in range(attempts):
        try:
            return fn()
        except ProviderNotConfigured:
            raise
        except retry_on as exc:
            if i == attempts - 1:
                raise
            delay = base_delay * (2 ** i)
            logger.warning("%s failed (%s) — retry %d/%d in %.0fs", label or "call", exc, i + 1, attempts - 1, delay)
            sleep(delay)
    raise AssertionError("unreachable")
