"""Tests for LLM forecast parsing, validation, retry and track-record scoring — no API calls."""

import json
from datetime import date

import pandas as pd
import pytest

import stockiq.backend.llm.providers as providers
from stockiq.backend.llm.track_record import load_forecasts, log_forecast, score_forecasts
from stockiq.backend.llm.validation import ForecastValidationError, parse_forecast, validate_forecast

TODAY = date(2026, 10, 12)   # Monday


def _days(n=10, start="2026-10-12", price=600.0, **override):
    dates = pd.bdate_range(start, periods=n)
    out = []
    for i, d in enumerate(dates, start=1):
        row = {
            "date": d.date().isoformat(), "direction": "Bullish", "est_close": price + i,
            "range_low": price + i - 2 * i, "range_high": price + i + 2 * i,
            "confidence": "Medium", "reason": "Above MA50; positive GEX",
        }
        row.update(override)
        out.append(row)
    return out


# ── parse ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("wrap", [
    lambda j: j,
    lambda j: f"```json\n{j}\n```",
    lambda j: f"Here is the forecast:\n{j}\nGood luck!",
])
def test_parse_handles_array_object_fences_and_prose(wrap):
    days = _days()
    assert parse_forecast(wrap(json.dumps(days))) == days
    assert parse_forecast(wrap(json.dumps({"days": days}))) == days


def test_parse_raises_without_json():
    with pytest.raises(ValueError):
        parse_forecast("I cannot forecast markets.")


# ── validate ──────────────────────────────────────────────────────────────────

def test_valid_forecast_passes_and_normalises():
    days = _days(direction="bullish", confidence="HIGH")
    check = validate_forecast(days, anchor_price=600, today=TODAY)
    assert check.ok, check.errors
    assert check.days[0]["direction"] == "Bullish" and check.days[0]["confidence"] == "High"


def test_wrong_count_weekend_and_order_are_errors():
    days = _days(9)
    days[3]["date"] = "2026-10-17"  # Saturday, and out of order
    errs = " ".join(validate_forecast(days, 600, TODAY).errors)
    assert "exactly 10" in errs and "weekend" in errs and "not after" in errs


def test_hallucinated_price_is_an_error():
    days = _days()
    days[9]["est_close"] = 6000   # off by 10×
    days[9]["range_high"] = 6100
    check = validate_forecast(days, 600, TODAY)
    assert any("from live price" in e for e in check.errors)


def test_inverted_range_and_est_outside_range_are_repaired():
    days = _days()
    days[0]["range_low"], days[0]["range_high"] = 610, 590    # inverted
    days[1]["est_close"] = 700                               # outside range (but < 20% drift)
    check = validate_forecast(days, 600, TODAY)
    assert check.ok
    assert check.days[0]["range_low"] == 590 and check.days[1]["range_high"] == 700
    assert len(check.repairs) >= 2


def test_bad_enums_and_numbers():
    days = _days()
    days[2]["direction"] = "Up"
    days[4]["est_close"] = "n/a"
    errs = " ".join(validate_forecast(days, 600, TODAY).errors)
    assert "direction" in errs and "positive numbers" in errs


# ── generate_forecast retry loop & fetch_ai_prediction caching ─────────────────

@pytest.fixture
def ctx():
    return json.dumps({"spy_live_price": 600.0})


def test_retry_once_with_errors_fed_back(monkeypatch, ctx):
    calls = []

    def fake(system, user, key):
        calls.append(user)
        return json.dumps({"days": _days(9 if len(calls) == 1 else 10, start=date.today().isoformat())})

    monkeypatch.setitem(providers._CALLERS, "groq", fake)
    days = providers.generate_forecast("groq", ctx, "k")
    assert len(days) == 10 and len(calls) == 2
    assert "rejected" in calls[1] and "exactly 10" in calls[1]


def test_gives_up_after_second_bad_reply(monkeypatch, ctx):
    monkeypatch.setitem(providers._CALLERS, "groq", lambda s, u, k: "no json here")
    with pytest.raises(ForecastValidationError):
        providers.generate_forecast("groq", ctx, "k")


def test_fetch_caches_success_but_not_missing_key(monkeypatch, ctx, tmp_path):
    monkeypatch.setattr(providers, "_forecast_cache", providers.MemoryCache())
    monkeypatch.setattr(providers, "log_forecast", lambda *a, **k: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    calls = []

    def fake(system, user, key):
        calls.append(key)
        return json.dumps({"days": _days(start=date.today().isoformat())})

    monkeypatch.setitem(providers._CALLERS, "groq", fake)
    assert providers.fetch_ai_prediction("2026-10-12-10", ctx, "groq") == []   # no key → [] and not cached
    monkeypatch.setenv("GROQ_API_KEY", "app-key")
    assert len(providers.fetch_ai_prediction("2026-10-12-10", ctx, "groq")) == 10
    providers.fetch_ai_prediction("2026-10-12-10", ctx, "groq")
    assert calls == ["app-key"]                       # second call served from cache
    providers.fetch_ai_prediction("2026-10-12-10", ctx, "groq", _user_key="mine")
    assert calls == ["app-key", "mine"]               # personal key never gets the shared result


def test_model_override_env(monkeypatch):
    monkeypatch.setenv("STOCKIQ_MODEL_GEMINI", "gemini-9-pro")
    assert providers.model_for("gemini") == "gemini-9-pro"


# ── track record ──────────────────────────────────────────────────────────────

def test_log_and_score(tmp_path):
    log = tmp_path / "f.jsonl"
    days = [
        {"date": "2026-10-13", "direction": "Bullish", "est_close": 101, "range_low": 99, "range_high": 103},
        {"date": "2026-10-14", "direction": "Bearish", "est_close": 103, "range_low": 100, "range_high": 104},
        {"date": "2026-10-30", "direction": "Bullish", "est_close": 110, "range_low": 100, "range_high": 120},  # future
    ]
    log_forecast("groq", "llama", 100.0, days, path=log)
    records = load_forecasts(log)
    closes = pd.Series([100.0, 102.0, 102.1], index=pd.to_datetime(["2026-10-12", "2026-10-13", "2026-10-14"]))
    table = score_forecasts(records, closes).set_index("horizon")

    d1 = table.loc["Day 1"]
    assert d1["direction hit %"] == 100          # up 2% and said Bullish
    assert d1["close error %"] == pytest.approx(abs(101 - 102) / 102 * 100, abs=0.01)
    assert d1["no-change error %"] == pytest.approx(2 / 102 * 100, abs=0.01)
    d2 = table.loc["Days 2–5"]
    assert d2["direction hit %"] == 0            # +0.1% is Neutral, said Bearish
    assert d2["days scored"] == 1                # the future date isn't scored


# ── Anthropic request shape (mocked client) ───────────────────────────────────

def _fake_anthropic(monkeypatch, stop_reason="end_turn", text='{"days": []}'):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import anthropic

    client = MagicMock()
    client.beta.messages.create.return_value = SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="other"),
        content=[SimpleNamespace(type="text", text=text)],
    )
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: client)
    return client


def test_anthropic_uses_structured_output_and_fallback(monkeypatch):
    client = _fake_anthropic(monkeypatch)
    assert providers._complete_anthropic("sys", "user", "k") == '{"days": []}'
    kw = client.beta.messages.create.call_args.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["format"]["schema"]["required"] == ["days"]
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]


def test_anthropic_refusal_raises(monkeypatch):
    _fake_anthropic(monkeypatch, stop_reason="refusal")
    with pytest.raises(RuntimeError, match="declined"):
        providers._complete_anthropic("sys", "user", "k")
