"""Device-control tools — mocked subprocess + platform, no real system changes."""

from subprocess import CompletedProcess

import tools.device_control as dc
from tools.device_control import (
    lock_screen,
    set_brightness,
    set_do_not_disturb,
    set_mute,
    set_volume,
)
from tools.registry import AUTO_ALLOW_TOOLS, CONFIRM_REQUIRED_TOOLS, READ_ONLY_TOOLS


def _patch(monkeypatch, system="Windows", returncode=0, stderr=""):
    """Force the platform and capture the subprocess command. Returns the recorder."""
    monkeypatch.setattr(dc.platform, "system", lambda: system)
    rec: dict = {}

    def fake_run(cmd, **kwargs):
        rec["cmd"] = cmd
        return CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(dc.subprocess, "run", fake_run)
    return rec


def test_set_volume_windows_scales_and_clamps(monkeypatch):
    rec = _patch(monkeypatch)
    assert "30%" in set_volume(30)
    assert "SetVolume(0.3000)" in rec["cmd"][-1]
    # over-range clamps to 100
    assert "100%" in set_volume(150)
    assert "SetVolume(1.0000)" in rec["cmd"][-1]


def test_set_volume_rejects_non_numeric(monkeypatch):
    _patch(monkeypatch)
    assert "Refused" in set_volume("loud")


def test_set_volume_macos_uses_osascript(monkeypatch):
    rec = _patch(monkeypatch, system="Darwin")
    assert "45%" in set_volume(45)
    assert rec["cmd"][0] == "osascript"
    assert "output volume 45" in rec["cmd"][-1]


def test_set_volume_unsupported_platform(monkeypatch):
    _patch(monkeypatch, system="Linux")
    assert "isn't supported on Linux" in set_volume(50)


def test_set_mute_windows(monkeypatch):
    rec = _patch(monkeypatch)
    assert "Muted" in set_mute(True)
    assert "SetMute($true)" in rec["cmd"][-1]
    assert "Unmuted" in set_mute(False)
    assert "SetMute($false)" in rec["cmd"][-1]


def test_set_brightness_windows(monkeypatch):
    rec = _patch(monkeypatch)
    assert "70%" in set_brightness(70)
    assert "WmiSetBrightness(1,70)" in rec["cmd"][-1]


def test_set_brightness_failure_explains(monkeypatch):
    _patch(monkeypatch, returncode=1, stderr="no WMI brightness")
    msg = set_brightness(50)
    assert "Couldn't set brightness" in msg
    assert "no WMI brightness" in msg


def test_do_not_disturb_toggles_toast_value(monkeypatch):
    rec = _patch(monkeypatch)
    assert "Do Not Disturb on" in set_do_not_disturb(True)
    assert "Value 0" in rec["cmd"][-1]
    assert "Do Not Disturb off" in set_do_not_disturb(False)
    assert "Value 1" in rec["cmd"][-1]


def test_lock_screen_windows(monkeypatch):
    rec = _patch(monkeypatch)
    assert "Locked" in lock_screen()
    assert rec["cmd"][0] == "rundll32.exe"


def test_lock_screen_failure(monkeypatch):
    _patch(monkeypatch, returncode=1, stderr="denied")
    assert "Couldn't lock" in lock_screen()


def test_device_tools_are_auto_allow():
    for name in ("set_volume", "set_mute", "set_brightness", "set_do_not_disturb", "lock_screen"):
        assert name in AUTO_ALLOW_TOOLS
        assert name not in READ_ONLY_TOOLS
        assert name not in CONFIRM_REQUIRED_TOOLS
