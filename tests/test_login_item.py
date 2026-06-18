"""tests/test_login_item.py — macOS Launch at login tools and API."""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client(temp_env):
    from dashboard.app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_login_tools_registered():
    from tools.registry import MODERATE_TOOLS, TOOL_DEFINITIONS

    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "enable_login_item" in names
    assert "disable_login_item" in names
    assert MODERATE_TOOLS >= {"enable_login_item", "disable_login_item"}


def test_moderate_tools_require_confirm_in_voice():
    from tools.registry import MODERATE_TOOLS, dispatch_tool

    with patch("tools.confirm.wait_for_confirm", return_value="deny") as mock_wait:
        result = dispatch_tool("enable_login_item", {}, confirm=True)
    mock_wait.assert_called_once()
    assert "not executed" in result


def test_enable_login_item_non_macos():
    with patch("platform.system", return_value="Windows"):
        from tools.login_item import enable_login_item

        assert "macOS only" in enable_login_item()


def test_build_launch_agent_plist_dev_mode(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("# jarvis\n", encoding="utf-8")
    venv_bin = root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = venv_bin / "python"
    python.write_text("", encoding="utf-8")

    monkeypatch.setattr("paths.bundle_root", lambda: root)
    monkeypatch.setattr("paths.user_data_root", lambda: root)
    monkeypatch.setattr("paths.is_frozen", lambda: False)
    monkeypatch.setattr(sys, "executable", str(python))

    from tools.login_item import build_launch_agent_plist

    plist = build_launch_agent_plist()
    assert plist["Label"] == "com.jarvis.app"
    assert plist["ProgramArguments"][0].endswith("/.venv/bin/python")
    assert plist["ProgramArguments"][1].endswith("/main.py")
    assert plist["WorkingDirectory"] == str(root)
    assert plist["EnvironmentVariables"]["JARVIS_LAUNCHD"] == "1"
    assert ".venv/bin" in plist["EnvironmentVariables"]["PATH"]


def test_build_launch_agent_plist_frozen_mode(tmp_path, monkeypatch):
    exe = tmp_path / "Jarvis.app" / "Contents" / "MacOS" / "Jarvis"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    support = tmp_path / "Library" / "Application Support" / "Jarvis"
    support.mkdir(parents=True)

    monkeypatch.setattr("paths.is_frozen", lambda: True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("HOME", str(tmp_path))

    from tools.login_item import build_launch_agent_plist

    plist = build_launch_agent_plist()
    assert plist["ProgramArguments"] == [str(exe.resolve())]
    assert plist["WorkingDirectory"] == str(support)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_write_launch_agent_plist(tmp_path, monkeypatch):
    plist_path = tmp_path / "LaunchAgents" / "com.jarvis.app.plist"
    monkeypatch.setattr("tools.login_item.launch_agent_plist_path", lambda: plist_path)
    monkeypatch.setattr(
        "tools.login_item.build_launch_agent_plist",
        lambda: {"Label": "com.jarvis.app", "ProgramArguments": ["/bin/echo", "jarvis"]},
    )

    from tools.login_item import write_launch_agent_plist

    written = write_launch_agent_plist()
    assert written == plist_path
    data = plistlib.loads(plist_path.read_bytes())
    assert data["Label"] == "com.jarvis.app"


def test_enable_login_item_calls_launchctl(tmp_path, monkeypatch):
    plist_path = tmp_path / "com.jarvis.app.plist"
    plist_path.write_bytes(plistlib.dumps({"Label": "com.jarvis.app"}))

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("tools.login_item.write_launch_agent_plist", lambda path=None: plist_path)
    monkeypatch.setattr(
        "tools.login_item._run_launchctl",
        lambda *args: MagicMock(returncode=0, stdout="", stderr=""),
    )

    from tools.login_item import enable_login_item

    result = enable_login_item()
    assert "enabled" in result.lower()


def test_disable_login_item_removes_plist(tmp_path, monkeypatch):
    plist_path = tmp_path / "com.jarvis.app.plist"
    plist_path.write_bytes(plistlib.dumps({"Label": "com.jarvis.app"}))

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("tools.login_item.launch_agent_plist_path", lambda: plist_path)
    monkeypatch.setattr("tools.login_item._run_launchctl", lambda *args: MagicMock(returncode=0, stdout="", stderr=""))

    from tools.login_item import disable_login_item

    result = disable_login_item()
    assert not plist_path.exists()
    assert "disabled" in result.lower()


def test_api_login_item_get(client, temp_env):
    with patch("tools.login_item.is_login_item_enabled", return_value=False), \
         patch("platform.system", return_value="Darwin"), \
         patch("paths.launch_at_login_mode", return_value="dev"):
        data = client.get("/api/login-item").get_json()
    assert data["supported"] is True
    assert data["enabled"] is False
    assert data["mode"] == "dev"


def test_api_login_item_post_enable(client, temp_env):
    with patch("tools.login_item.enable_login_item", return_value="Launch at login enabled (dev)."), \
         patch("tools.login_item.is_login_item_enabled", return_value=True), \
         patch("platform.system", return_value="Darwin"):
        data = client.post("/api/login-item", json={"enabled": True}).get_json()
    assert data["ok"] is True
    assert data["enabled"] is True


def test_api_login_item_post_disable(client, temp_env):
    with patch("tools.login_item.disable_login_item", return_value="Launch at login disabled."), \
         patch("tools.login_item.is_login_item_enabled", return_value=False), \
         patch("platform.system", return_value="Darwin"):
        data = client.post("/api/login-item", json={"enabled": False}).get_json()
    assert data["ok"] is True
    assert data["enabled"] is False
