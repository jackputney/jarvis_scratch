"""Unit tests for improvement.judge (no API calls)."""

from improvement.judge import judge_turn


def test_judge_must_use_tool_pass():
    golden = {"id": "t1", "must_use_tool": "get_current_time"}
    out = judge_turn(golden, "It's 3pm.", ["get_current_time"], use_haiku=False)
    assert out["pass"] is True
    assert out["case_id"] == "t1"


def test_judge_must_use_tool_fail():
    golden = {"id": "t2", "must_use_tool": "get_weather"}
    out = judge_turn(golden, "Sunny.", [], use_haiku=False)
    assert out["pass"] is False
    assert "get_weather" in out["reason"]


def test_judge_max_words():
    golden = {"id": "t3", "max_words": 5}
    out = judge_turn(golden, "one two three four five six", [], use_haiku=False)
    assert out["pass"] is False


def test_judge_must_not_contain():
    golden = {"id": "t4", "must_not_contain": ["I don't have access"]}
    out = judge_turn(
        golden,
        "I don't have access to that.",
        [],
        use_haiku=False,
    )
    assert out["pass"] is False


def test_judge_must_not_use_tool():
    golden = {"id": "t5", "must_not_use_tool": True}
    out = judge_turn(golden, "Hello!", ["open_app"], use_haiku=False)
    assert out["pass"] is False
