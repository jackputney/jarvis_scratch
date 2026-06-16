"""Time and date tool tests."""

from tools.registry import READ_ONLY_TOOLS, TOOL_DEFINITIONS
from tools.time_date import get_current_time


def test_get_current_time_returns_formatted():
    result = get_current_time()
    assert "Current date:" in result
    assert "Current time:" in result
    assert "Timezone:" in result
    assert "Unix timestamp:" in result


def test_get_current_time_contains_day_of_week():
    result = get_current_time()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    assert any(day in result for day in days)


def test_get_current_time_registered():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert "get_current_time" in names
    assert "get_current_time" in READ_ONLY_TOOLS


def test_get_current_time_empty_timezone():
    result = get_current_time(timezone="")
    assert "Current time:" in result
