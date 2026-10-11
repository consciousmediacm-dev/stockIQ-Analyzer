"""
Parse and validate LLM forecast output.

LLMs occasionally return prose around the JSON, 9 days instead of 10, weekend
dates, ranges that don't contain the estimate, or a price off by an order of
magnitude. parse_forecast() extracts the JSON; validate_forecast() repairs the
harmless problems and reports the serious ones so the caller can retry once
with the errors fed back to the model.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date

FORECAST_DAYS = 10
DIRECTIONS = {"bullish": "Bullish", "bearish": "Bearish", "neutral": "Neutral"}
CONFIDENCES = {"high": "High", "medium": "Medium", "low": "Low"}
REQUIRED_KEYS = ("date", "direction", "est_close", "range_low", "range_high", "confidence", "reason")
# Day-10 SPY close more than this far from the live price is treated as a hallucination
MAX_DRIFT = 0.20

# JSON schema used for providers that support structured outputs (Anthropic).
# Array length isn't expressible in structured-output schemas — validate_forecast enforces it.
FORECAST_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date":       {"type": "string", "format": "date"},
                    "direction":  {"type": "string", "enum": ["Bullish", "Bearish", "Neutral"]},
                    "est_close":  {"type": "number"},
                    "range_low":  {"type": "number"},
                    "range_high": {"type": "number"},
                    "confidence": {"type": "string", "enum": ["High", "Medium", "Low"]},
                    "reason":     {"type": "string"},
                },
                "required": list(REQUIRED_KEYS),
                "additionalProperties": False,
            },
        },
    },
    "required": ["days"],
    "additionalProperties": False,
}


class ForecastValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class ForecastCheck:
    days: list[dict]
    errors: list[str] = field(default_factory=list)     # serious → retry / reject
    repairs: list[str] = field(default_factory=list)    # fixed silently, logged

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_forecast(text: str) -> list[dict]:
    """
    Extract the list of day objects from a model reply. Accepts a bare array,
    {"days": [...]}, markdown fences, or JSON embedded in prose.
    Raises ValueError when no JSON can be found.
    """
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    for candidate in (text, _outermost(text, "{", "}"), _outermost(text, "[", "]")):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            for key in ("days", "forecast", "predictions"):
                if isinstance(data.get(key), list):
                    return data[key]
        if isinstance(data, list):
            return data
    raise ValueError("no JSON forecast found in model output")


def _outermost(text: str, open_ch: str, close_ch: str) -> str | None:
    i, j = text.find(open_ch), text.rfind(close_ch)
    return text[i:j + 1] if 0 <= i < j else None


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def validate_forecast(days: list, anchor_price: float | None, today: date | None = None) -> ForecastCheck:
    today = today or date.today()
    errors: list[str] = []
    repairs: list[str] = []
    clean: list[dict] = []

    if not isinstance(days, list):
        return ForecastCheck([], ["output is not a list of days"])
    if len(days) != FORECAST_DAYS:
        errors.append(f"expected exactly {FORECAST_DAYS} days, got {len(days)}")

    prev_date: date | None = None
    prev_width: float | None = None
    for i, d in enumerate(days, start=1):
        if not isinstance(d, dict):
            errors.append(f"day {i}: not an object")
            continue
        missing = [k for k in REQUIRED_KEYS if k not in d]
        if missing:
            errors.append(f"day {i}: missing {missing}")
            continue

        try:
            dt = date.fromisoformat(str(d["date"])[:10])
        except ValueError:
            errors.append(f"day {i}: bad date {d['date']!r}")
            continue
        if dt.weekday() >= 5:
            errors.append(f"day {i}: {dt} is a weekend")
        if prev_date and dt <= prev_date:
            errors.append(f"day {i}: {dt} is not after {prev_date}")
        if i == 1 and (dt - today).days > 4:
            errors.append(f"day 1 is {dt}, more than a few days after today ({today})")
        prev_date = dt

        direction = DIRECTIONS.get(str(d["direction"]).strip().lower())
        confidence = CONFIDENCES.get(str(d["confidence"]).strip().lower())
        if not direction:
            errors.append(f"day {i}: direction {d['direction']!r} not Bullish/Bearish/Neutral")
        if not confidence:
            errors.append(f"day {i}: confidence {d['confidence']!r} not High/Medium/Low")

        est, lo, hi = _num(d["est_close"]), _num(d["range_low"]), _num(d["range_high"])
        if None in (est, lo, hi):
            errors.append(f"day {i}: est_close/range_low/range_high must be positive numbers")
            continue
        if lo > hi:
            lo, hi = hi, lo
            repairs.append(f"day {i}: swapped inverted range")
        if not lo <= est <= hi:
            lo, hi = min(lo, est), max(hi, est)
            repairs.append(f"day {i}: widened range to contain est_close")
        if anchor_price and abs(est / anchor_price - 1) > MAX_DRIFT:
            errors.append(f"day {i}: est_close {est:.2f} is >{MAX_DRIFT:.0%} from live price {anchor_price:.2f}")
        width = hi - lo
        if prev_width is not None and width < prev_width:
            repairs.append(f"day {i}: range narrower than day {i - 1} (prompt asks for widening)")
        prev_width = width

        clean.append({
            "date":       dt.isoformat(),
            "direction":  direction or "Neutral",
            "est_close":  round(est, 2),
            "range_low":  round(lo, 2),
            "range_high": round(hi, 2),
            "confidence": confidence or "Low",
            "reason":     str(d["reason"]).strip()[:200],
        })

    return ForecastCheck(clean, errors, repairs)
