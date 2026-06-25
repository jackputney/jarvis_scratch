"""macOS device-control extensions — mocked subprocess, no real system changes."""

from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import platform
import pytest

import tools.device_control as dc
from tools.device_control import get_battery_status, get_system_info, set_appearance_mode, set_wifi
from tools.registry import AUTO_ALLOW_TOOLS, READ_ONLY_TOOLS, TOOL_DEFINITIONS


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
def test_get_battery_status_returns_string():
    with patch("tools.device_control.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="100%; charged", returncode=0, stderr="")
        result = get_battery_status()
        assert isinstance(result, str)
        assert len(result) > 0


def test_get_battery_status_windows_graceful():
    with patch.object(dc.platform, "system", return_value="Windows"):
        result = get_battery_status()
        assert "macOS only" in result


def test_set_appearance_mode_registered():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert "set_appearance_mode" in names


def test_get_system_info_registered():
    assert "get_system_info" in READ_ONLY_TOOLS


def test_set_wifi_registered():
    assert "set_wifi" in AUTO_ALLOW_TOOLS


def test_set_appearance_mode_dark(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")
    rec: dict = {}

    def fake_run(cmd, **kwargs):
        rec["cmd"] = cmd
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(dc.subprocess, "run", fake_run)
    assert "dark" in set_appearance_mode("dark")
    assert rec["cmd"][0] == "osascript"


def test_set_wifi_invalid_action(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")
    assert "Refused" in set_wifi("toggle")


def test_set_wifi_detects_interface_dynamically(monkeypatch):
    """Regression: set_wifi previously hardcoded en0; now detects via networksetup."""
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")

    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "-listallhardwareports" in cmd:
            return CompletedProcess(cmd, 0, stdout="Hardware Port: Wi-Fi\nDevice: en1\n", stderr="")
        # the actual setairportpower call
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(dc.subprocess, "run", fake_run)
    result = set_wifi("off")
    assert "WiFi turned off" in result
    setairport_call = [c for c in calls if "-setairportpower" in c][0]
    assert "en1" in setairport_call  # used detected interface, not hardcoded en0


def test_set_brightness_windows_path(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "Windows")

    def fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(dc.subprocess, "run", fake_run)
    result = dc.set_brightness(75)
    assert "75%" in result


def test_set_brightness_macos_osascript_path(monkeypatch):
    """macOS brightness now has a branch (previously Windows-only)."""
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")

    def fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(dc.subprocess, "run", fake_run)
    result = dc.set_brightness(50)
    assert "50%" in result


def test_set_brightness_macos_osascript_failure_fallback(monkeypatch):
    """Falls back to brightness CLI if osascript fails, returns helpful message if both fail."""
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")
    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return CompletedProcess(cmd, 1, stdout="", stderr="not supported")

    monkeypatch.setattr(dc.subprocess, "run", fake_run)
    result = dc.set_brightness(50)
    assert "Couldn't set brightness" in result or "brew install brightness" in result
