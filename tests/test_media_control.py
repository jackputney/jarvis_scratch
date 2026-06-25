"""tests/test_media_control.py — Windows global media key tool."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import tools.media_control as media_control_mod
from tools.media_control import media_control
from tools.registry import MODERATE_TOOLS, TOOL_DEFINITIONS, dispatch_tool


def test_media_control_registered():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "media_control" in names
    assert "media_control" in MODERATE_TOOLS


def test_moderate_media_control_requires_confirm_in_voice():
    with patch("tools.confirm.wait_for_confirm", return_value="deny") as mock_wait:
        result = dispatch_tool("media_control", {"action": "play"}, confirm=True)
    mock_wait.assert_called_once()
    assert "not executed" in result


def test_media_control_non_windows():
    with patch.object(media_control_mod.platform, "system", return_value="Darwin"):
        assert media_control("play") == media_control_mod._NOT_WINDOWS


def test_media_control_invalid_action():
    with patch.object(media_control_mod.platform, "system", return_value="Windows"):
        assert "Refused" in media_control("volume_up")


@pytest.mark.parametrize(
    "action,expected_vk",
    [
        ("play", media_control_mod.VK_MEDIA_PLAY_PAUSE),
        ("pause", media_control_mod.VK_MEDIA_PLAY_PAUSE),
        ("play_pause", media_control_mod.VK_MEDIA_PLAY_PAUSE),
        ("skip", media_control_mod.VK_MEDIA_NEXT_TRACK),
        ("next", media_control_mod.VK_MEDIA_NEXT_TRACK),
        ("previous", media_control_mod.VK_MEDIA_PREV_TRACK),
        ("prev", media_control_mod.VK_MEDIA_PREV_TRACK),
    ],
)
def test_media_control_sends_key(action, expected_vk, monkeypatch):
    monkeypatch.setattr(media_control_mod.platform, "system", lambda: "Windows")
    rec: dict = {}

    def fake_send(vk_code: int) -> None:
        rec["vk"] = vk_code

    monkeypatch.setattr(media_control_mod, "_send_media_key", fake_send)
    result = media_control(action)
    assert rec["vk"] == expected_vk
    assert "Sent media key" in result


def test_media_control_send_failure(monkeypatch):
    monkeypatch.setattr(media_control_mod.platform, "system", lambda: "Windows")

    def fake_send(vk_code: int) -> None:
        raise OSError("SendInput returned 0")

    monkeypatch.setattr(media_control_mod, "_send_media_key", fake_send)
    result = media_control("skip")
    assert result.startswith("Media control error:")
