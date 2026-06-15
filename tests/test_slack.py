"""Slack integration tools — mocked API."""

import os
from unittest.mock import MagicMock, patch

from tools.registry import CONFIRM_REQUIRED_TOOLS, READ_ONLY_TOOLS
from tools.slack import read_slack_channel, send_slack_message


def test_slack_send_mocked(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("requests.post", return_value=mock_resp):
        result = send_slack_message("#general", "Hello")
    assert "sent" in result.lower()


def test_slack_read_mocked(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "ok": True,
        "messages": [{"user": "U1", "text": "Standup at 9"}],
    }
    with patch("requests.get", return_value=mock_resp):
        result = read_slack_channel("#general", 5)
    assert "Standup at 9" in result


def test_slack_missing_token_returns_error(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    assert "not configured" in send_slack_message("#general", "Hi").lower()
    assert "send_slack_message" in CONFIRM_REQUIRED_TOOLS
    assert "read_slack_channel" in READ_ONLY_TOOLS
