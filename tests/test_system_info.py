"""tests/test_system_info.py — PC info tools with mocked psutil/ctypes."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import tools.system_info as system_info_mod
from tools.registry import READ_ONLY_TOOLS, TOOL_DEFINITIONS


def test_system_info_tools_registered():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert {"system_info", "list_processes", "active_window"} <= names
    assert {"system_info", "list_processes", "active_window"} <= READ_ONLY_TOOLS


def test_system_info_reports_usage(monkeypatch):
    fake_mem = SimpleNamespace(percent=42.5, used=4_294_967_296, total=8_589_934_592)
    fake_disk = SimpleNamespace(percent=55.0, used=100_000_000_000, total=500_000_000_000)
    fake_psutil = MagicMock()
    fake_psutil.cpu_percent.return_value = 12.3
    fake_psutil.virtual_memory.return_value = fake_mem
    fake_psutil.disk_usage.return_value = fake_disk
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    from tools.system_info import system_info

    result = system_info()
    assert "CPU: 12.3%" in result
    assert "RAM: 42.5%" in result
    assert "Disk" in result


def test_list_processes_top_twenty(monkeypatch):
    procs = []
    for idx in range(25):
        proc = MagicMock()
        proc.info = {"pid": 1000 + idx, "name": f"proc{idx}", "cpu_percent": float(idx)}
        procs.append(proc)

    fake_psutil = MagicMock()
    fake_psutil.process_iter.return_value = procs
    fake_psutil.NoSuchProcess = Exception
    fake_psutil.AccessDenied = Exception
    fake_psutil.ZombieProcess = Exception
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    from tools.system_info import list_processes

    result = list_processes()
    assert "Top processes by CPU:" in result
    lines = [line for line in result.splitlines() if line.strip().startswith("proc")]
    assert len(lines) == 20
    assert "proc24" in result
    assert "proc4" not in result


def test_active_window_non_windows():
    with patch.object(system_info_mod.platform, "system", return_value="Darwin"):
        from tools.system_info import active_window

        assert active_window() == system_info_mod._NOT_WINDOWS


def test_active_window_windows(monkeypatch):
    monkeypatch.setattr(system_info_mod.platform, "system", lambda: "Windows")

    class FakeUser32:
        def GetForegroundWindow(self):
            return 123

        def GetWindowTextLengthW(self, hwnd):
            assert hwnd == 123
            return len("Spotify")

        def GetWindowTextW(self, hwnd, buf, length):
            buf.value = "Spotify"

    fake_ctypes = MagicMock()
    fake_ctypes.windll.user32 = FakeUser32()
    fake_ctypes.create_unicode_buffer = __import__("ctypes").create_unicode_buffer
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    from tools.system_info import active_window

    assert active_window() == "Spotify"
