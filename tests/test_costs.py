"""Cost math + spend accounting smoke tests."""

import pytest

import costs


def test_cost_math_haiku():
    # $1 in / $5 out per Mtok → 1M each = $6.00
    assert costs.compute_cost("claude-haiku-4-5", 1_000_000, 1_000_000) == pytest.approx(6.0)


def test_cost_math_sonnet():
    # $3 in / $15 out per Mtok → 1M each = $18.00
    assert costs.compute_cost("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_unknown_model_uses_sonnet_pricing():
    # Safest fallback is the most expensive tier so spend is never under-counted.
    assert costs.compute_cost("mystery-model", 1_000_000, 0) == pytest.approx(3.0)


def test_partial_token_cost():
    # 1500 input + 500 output on haiku = 1500*1/1e6 + 500*5/1e6 = 0.004
    assert costs.compute_cost("claude-haiku-4-5", 1500, 500) == pytest.approx(0.004)


def test_log_usage_reads_real_tokens_and_persists(temp_env):
    cost = costs.log_usage(
        "claude-haiku-4-5",
        {"input_tokens": 1_000_000, "output_tokens": 0},
        "what's the weather",
    )
    assert cost == pytest.approx(1.0)
    assert costs.get_spend("today") == pytest.approx(1.0)
    assert costs.get_spend("month") == pytest.approx(1.0)


def test_log_usage_accepts_object_usage(temp_env):
    class Usage:
        input_tokens = 0
        output_tokens = 1_000_000

    cost = costs.log_usage("claude-sonnet-4-6", Usage(), "essay")
    assert cost == pytest.approx(15.0)


def test_spend_summary_pct(temp_env):
    costs.log_usage("claude-haiku-4-5", {"input_tokens": 1_000_000, "output_tokens": 0}, "x")
    summary = costs.get_spend_summary(daily_budget=2.0, monthly_budget=40.0)
    assert summary["today"] == pytest.approx(1.0)
    assert summary["daily_pct"] == pytest.approx(50.0)


def test_daily_tool_count(temp_env):
    costs.log_tool_run("web_search", {"query": "jarvis"}, "ok", True)
    costs.log_tool_run("get_variable", {"key": "x"}, "done", True)
    assert costs.get_daily_tool_count() == 2


def test_daily_query_count(temp_env):
    import events

    events.record_conversation("hello", "hi back", "claude-haiku-4-5", 42, 0.001)
    assert costs.get_daily_query_count() >= 1
