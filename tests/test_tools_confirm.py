"""Tool confirm gate — read-only tools must not block voice on input()."""

from unittest.mock import patch

from tools.registry import READ_ONLY_TOOLS, dispatch_tool


def test_read_only_tools_skip_confirm():
    assert "get_variable" in READ_ONLY_TOOLS
    assert "web_search" in READ_ONLY_TOOLS
    with patch("builtins.input") as mock_input:
        dispatch_tool("get_variable", {"key": "nonexistent_test_key_xyz"}, confirm=True)
        mock_input.assert_not_called()


def test_mutating_tools_still_confirm():
    with patch("builtins.input", side_effect=EOFError):
        result = dispatch_tool("set_variable", {"key": "x", "value": "y"}, confirm=True)
    assert "not executed" in result
