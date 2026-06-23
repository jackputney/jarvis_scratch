"""Tool confirm tiers — read-only/auto-allow vs dashboard confirm."""

from unittest.mock import patch

from tools.registry import (
    AUTO_ALLOW_TOOLS,
    CONFIRM_REQUIRED_TOOLS,
    READ_ONLY_TOOLS,
    dispatch_tool,
)


def test_read_only_tools_skip_confirm():
    assert "get_variable" in READ_ONLY_TOOLS
    assert "web_search" in READ_ONLY_TOOLS
    with patch("tools.confirm.wait_for_confirm") as mock_wait:
        dispatch_tool("get_variable", {"key": "nonexistent_test_key_xyz"}, confirm=True)
        mock_wait.assert_not_called()


def test_auto_allow_tools_skip_dashboard_confirm():
    assert AUTO_ALLOW_TOOLS >= {"open_app", "set_variable", "write_note", "send_email"}
    with patch("tools.confirm.wait_for_confirm") as mock_wait:
        dispatch_tool("write_note", {"title": "t", "content": "c"}, confirm=True)
        mock_wait.assert_not_called()


def test_high_risk_tools_use_dashboard_confirm():
    assert "append_row" in CONFIRM_REQUIRED_TOOLS
    with patch("tools.confirm.wait_for_confirm", return_value="deny") as mock_wait:
        result = dispatch_tool(
            "append_row",
            {"spreadsheet_id": "id", "sheet_name": "S", "values": ["a"]},
            confirm=True,
            confirm_timeout_sec=30,
        )
        mock_wait.assert_called_once()
        assert "not executed" in result
        assert "denied" in result


def test_high_risk_timeout_message():
    with patch("tools.confirm.wait_for_confirm", return_value="timeout"):
        result = dispatch_tool(
            "append_row",
            {"spreadsheet_id": "id", "sheet_name": "S", "values": ["a"]},
            confirm=True,
            confirm_timeout_sec=30,
        )
    assert "timed out" in result
