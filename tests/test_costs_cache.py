"""Cache-aware cost accounting for prompt caching."""

from pytest import approx

import costs


def test_compute_cost_plain_input():
    cost = costs.compute_cost("claude-haiku-4-5", input_tokens=1000, output_tokens=200)
    assert cost == approx(0.002)  # (1000*1 + 200*5) / 1e6


def test_compute_cost_cache_read_discount():
    plain = costs.compute_cost("claude-sonnet-4-6", 0, 0, cache_read_tokens=10_000)
    full = costs.compute_cost("claude-sonnet-4-6", 10_000, 0)
    assert plain < full
    assert plain == approx(10_000 * 3.0 * 0.10 / 1_000_000)


def test_compute_cost_cache_write_premium():
    write = costs.compute_cost("claude-sonnet-4-6", 0, 0, cache_write_tokens=1000)
    read_equiv = costs.compute_cost("claude-sonnet-4-6", 1000, 0)
    assert write > read_equiv
    assert write == approx(1000 * 3.0 * 1.25 / 1_000_000)


def test_log_usage_includes_cached_tokens_in_input_count(temp_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    logged: list[tuple] = []

    class FakeConn:
        def execute(self, sql, params):
            logged.append(params)
            return self

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(costs, "_connect", lambda: FakeConn())
    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 900,
    }
    cost = costs.log_usage("claude-sonnet-4-6", usage, "hello")
    assert cost > 0
    assert logged[0][2] == 1000  # input_tokens column = uncached + cache read
