"""Events deque + conversation persistence smoke tests."""

import events


def test_deque_is_bounded(temp_env):
    for i in range(events.MAX_EVENTS + 80):
        events.emit("tick", n=i)
    recent = events.get_recent_events(10_000)
    assert len(recent) <= events.MAX_EVENTS


def test_state_snapshot_has_uptime(temp_env):
    events.set_pipeline_state("LISTENING")
    events.set_muted(True)
    state = events.get_state()
    assert state["pipeline_state"] == "LISTENING"
    assert state["muted"] is True
    assert isinstance(state["uptime_seconds"], int)


def test_record_conversation_persists(temp_env):
    events.record_conversation("hi", "hello", "claude-haiku-4-5", 320, 0.0012)
    rows = events.get_recent_conversations(50)
    assert len(rows) == 1
    row = rows[0]
    assert row["heard"] == "hi"
    assert row["response"] == "hello"
    assert row["model"] == "claude-haiku-4-5"
    assert row["latency_ms"] == 320
    assert row["cost_usd"] == 0.0012


def test_recent_conversations_limit_and_order(temp_env):
    for i in range(60):
        events.record_conversation(f"q{i}", f"a{i}", "m", i, 0.0)
    rows = events.get_recent_conversations(50)
    assert len(rows) == 50
    # newest last
    assert rows[-1]["heard"] == "q59"
