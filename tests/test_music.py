"""tests/test_music.py — Music tools (mocked AppleScript / Spotify URI)."""

from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

import tools.music as music
from tools.music import (
    get_now_playing,
    pause,
    play,
    previous,
    search_and_play,
    set_volume,
    skip,
)
from tools.registry import MODERATE_TOOLS, TOOL_DEFINITIONS, dispatch_tool

_MUSIC_TOOLS = {
    "music_play",
    "music_pause",
    "music_skip",
    "music_previous",
    "music_set_volume",
    "get_now_playing",
    "search_and_play",
}


@pytest.fixture
def client(temp_env):
    from dashboard.app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_music_tools_registered():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert _MUSIC_TOOLS <= names
    assert _MUSIC_TOOLS <= MODERATE_TOOLS


def test_moderate_music_tools_require_confirm_in_voice():
    with patch("tools.confirm.wait_for_confirm", return_value="deny") as mock_wait:
        result = dispatch_tool("music_play", {}, confirm=True)
    mock_wait.assert_called_once()
    assert "not executed" in result


def test_play_non_macos():
    with patch.object(music.platform, "system", return_value="Linux"):
        assert play() == music._NOT_MAC


def test_pause_non_macos():
    with patch.object(music.platform, "system", return_value="Windows"):
        assert pause() == music._NOT_MAC


def test_skip_non_macos():
    with patch.object(music.platform, "system", return_value="Windows"):
        assert skip() == music._NOT_MAC


def test_previous_non_macos():
    with patch.object(music.platform, "system", return_value="Windows"):
        assert previous() == music._NOT_MAC


def test_set_volume_non_macos():
    with patch.object(music.platform, "system", return_value="Windows"):
        assert set_volume(50) == music._NOT_MAC


def test_get_now_playing_windows():
    with patch.object(music.platform, "system", return_value="Windows"):
        assert get_now_playing() == music._NOT_WINDOWS


def test_get_now_playing_non_supported_os():
    with patch.object(music.platform, "system", return_value="Linux"):
        assert get_now_playing() == music._NOT_MAC


def test_play_calls_osascript(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Darwin")
    rec: dict = {}

    def fake_run(cmd, **kwargs):
        rec["cmd"] = cmd
        return CompletedProcess(cmd, 0, stdout="playing\n", stderr="")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    assert play() == "playing"
    assert rec["cmd"][:2] == ["osascript", "-e"]
    assert 'tell application "Music" to play' in rec["cmd"][2]


def test_pause_calls_osascript(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Darwin")

    def fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    assert pause() == "Done."


def test_skip_calls_osascript(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Darwin")
    rec: dict = {}

    def fake_run(cmd, **kwargs):
        rec["script"] = cmd[2]
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    skip()
    assert "next track" in rec["script"]


def test_previous_calls_osascript(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Darwin")
    rec: dict = {}

    def fake_run(cmd, **kwargs):
        rec["script"] = cmd[2]
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    previous()
    assert "previous track" in rec["script"]


def test_set_volume_clamps_and_calls_osascript(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Darwin")
    rec: dict = {}

    def fake_run(cmd, **kwargs):
        rec["script"] = cmd[2]
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    set_volume(150)
    assert "sound volume to 100" in rec["script"]
    set_volume(-5)
    assert "sound volume to 0" in rec["script"]


def test_get_now_playing_macos(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Darwin")

    def fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 0, stdout="Song — Artist · Album\n", stderr="")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    assert get_now_playing() == "Song — Artist · Album"


def test_applescript_error_surfaces(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Darwin")

    def fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 1, stdout="", stderr="Music got an error: not running")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    result = play()
    assert result.startswith("Music error:")


def test_search_and_play_empty_query():
    assert "Refused" in search_and_play("   ")


def test_search_and_play_macos(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Darwin")
    rec: dict = {}

    def fake_run(cmd, **kwargs):
        rec["script"] = cmd[2]
        return CompletedProcess(cmd, 0, stdout="Playing: Track — Artist", stderr="")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    result = search_and_play('hello "world"')
    assert result == "Playing: Track — Artist"
    assert 'hello \\"world\\"' in rec["script"]
    assert "search library playlist 1" in rec["script"]


def test_search_and_play_windows_opens_spotify(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Windows")
    rec: dict = {}

    def fake_run(cmd, **kwargs):
        rec["cmd"] = cmd
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    result = search_and_play("daft punk")
    assert "Spotify search" in result
    assert rec["cmd"][:3] == ["cmd", "/c", "start"]
    assert rec["cmd"][4].startswith("spotify:search:")


def test_search_and_play_windows_failure(monkeypatch):
    monkeypatch.setattr(music.platform, "system", lambda: "Windows")

    def fake_run(cmd, **kwargs):
        raise OSError("no spotify")

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    assert "Could not open Spotify" in search_and_play("test")


def test_search_and_play_non_supported_os():
    with patch.object(music.platform, "system", return_value="Linux"):
        assert search_and_play("song") == music._NOT_MAC


def test_api_music_now_playing(client, temp_env):
    with patch("tools.music.get_now_playing", return_value="Track — Artist · Album"), \
         patch("platform.system", return_value="Darwin"):
        data = client.get("/api/music/now-playing").get_json()
    assert data["supported"] is True
    assert data["macos"] is True
    assert data["now_playing"] == "Track — Artist · Album"


def test_api_music_now_playing_windows(client, temp_env):
    with patch("tools.music.get_now_playing", return_value=music._NOT_WINDOWS), \
         patch("platform.system", return_value="Windows"):
        data = client.get("/api/music/now-playing").get_json()
    assert data["supported"] is True
    assert data["macos"] is False
    assert "not supported" in data["now_playing"].lower()
