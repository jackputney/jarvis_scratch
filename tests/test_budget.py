"""Budget enforcement smoke tests (the Anthropic call is mocked)."""

import pipeline
import costs
from config import Config


def _fake_call(reply="ok", model="claude-haiku-4-5", cost=0.001):
    def _inner(text, cfg, history=None):
        return reply, model, cost
    return _inner


def test_hard_stop_when_over_daily_budget(temp_env, monkeypatch):
    monkeypatch.setattr(costs, "get_spend", lambda period: 5.0)
    calls = []
    monkeypatch.setattr(pipeline, "_call_claude",
                        lambda text, cfg, history=None: calls.append(text) or ("hi", "m", 0.0))

    cfg = Config(daily_budget_usd=2.0)
    result = pipeline.process_query("hello", cfg)

    assert result["capped"] is True
    assert "budget cap" in result["reply"].lower()
    assert calls == []  # the API was never called — hard stop, no override


def test_under_budget_calls_api(temp_env, monkeypatch):
    monkeypatch.setattr(costs, "get_spend", lambda period: 0.10)
    monkeypatch.setattr(pipeline, "_call_claude", _fake_call(reply="four"))

    cfg = Config(daily_budget_usd=2.0)
    result = pipeline.process_query("two plus two", cfg)

    assert result["capped"] is False
    assert result["reply"] == "four"
    assert result["warning"] is None


def test_80_percent_warning_is_one_time(temp_env, monkeypatch):
    monkeypatch.setattr(costs, "get_spend", lambda period: 1.7)  # 85% of 2.00
    monkeypatch.setattr(pipeline, "_call_claude", _fake_call())
    pipeline._warn_state["date"] = None  # reset the daily one-shot

    cfg = Config(daily_budget_usd=2.0)
    first = pipeline.process_query("hi", cfg)
    second = pipeline.process_query("hi again", cfg)

    assert first["warning"] is not None
    assert "80 percent" in first["warning"]
    assert second["warning"] is None  # only once per day


def test_budget_level_thresholds(monkeypatch):
    cfg = Config(daily_budget_usd=2.0)
    monkeypatch.setattr(costs, "get_spend", lambda period: 0.0)
    assert pipeline.budget_level(cfg) == "normal"
    monkeypatch.setattr(costs, "get_spend", lambda period: 1.7)
    assert pipeline.budget_level(cfg) == "warn"
    monkeypatch.setattr(costs, "get_spend", lambda period: 2.5)
    assert pipeline.budget_level(cfg) == "capped"
