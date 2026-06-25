"""tests/test_clipboard.py — Clipboard read/write tools with mocked Win32 APIs."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import tools.clipboard as clipboard_mod
from tools.clipboard import read_clipboard, write_clipboard
from tools.registry import MODERATE_TOOLS, READ_ONLY_TOOLS, TOOL_DEFINITIONS, dispatch_tool


def test_clipboard_tools_registered():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "read_clipboard" in names
    assert "write_clipboard" in names
    assert "read_clipboard" in READ_ONLY_TOOLS
    assert "write_clipboard" in MODERATE_TOOLS


def test_write_clipboard_requires_confirm_in_voice():
    with patch("tools.confirm.wait_for_confirm", return_value="deny") as mock_wait:
        result = dispatch_tool("write_clipboard", {"text": "hello"}, confirm=True)
    mock_wait.assert_called_once()
    assert "not executed" in result


def test_read_clipboard_non_windows():
    with patch.object(clipboard_mod.platform, "system", return_value="Darwin"):
        assert read_clipboard() == clipboard_mod._NOT_WINDOWS


def test_write_clipboard_non_windows():
    with patch.object(clipboard_mod.platform, "system", return_value="Linux"):
        assert write_clipboard("hi") == clipboard_mod._NOT_WINDOWS


def test_write_clipboard_empty_text():
    with patch.object(clipboard_mod.platform, "system", return_value="Windows"):
        assert "Refused" in write_clipboard("   ")


def test_read_clipboard_returns_text(monkeypatch):
    monkeypatch.setattr(clipboard_mod.platform, "system", lambda: "Windows")

    class FakeKernel32:
        def GlobalLock(self, handle):
            return 1

        def GlobalUnlock(self, handle):
            return None

    class FakeUser32:
        def OpenClipboard(self, hwnd):
            return 1

        def GetClipboardData(self, fmt):
            return 99

        def CloseClipboard(self):
            return 1

    fake_ctypes = MagicMock()
    fake_ctypes.windll.user32 = FakeUser32()
    fake_ctypes.windll.kernel32 = FakeKernel32()
    fake_ctypes.wstring_at = lambda ptr: "hello clipboard"
    monkeypatch.setitem(__import__("sys").modules, "ctypes", fake_ctypes)

    assert read_clipboard() == "hello clipboard"


def test_write_clipboard_sets_text(monkeypatch):
    monkeypatch.setattr(clipboard_mod.platform, "system", lambda: "Windows")
    rec: dict = {}

    class FakeKernel32:
        def GlobalAlloc(self, flags, size):
            rec["size"] = size
            return 42

        def GlobalLock(self, handle):
            rec["handle"] = handle
            return 100

        def GlobalUnlock(self, handle):
            return None

        def GlobalFree(self, handle):
            rec["freed"] = handle

    class FakeUser32:
        def OpenClipboard(self, hwnd):
            return 1

        def EmptyClipboard(self):
            return 1

        def SetClipboardData(self, fmt, handle):
            rec["set"] = (fmt, handle)
            return 1

        def CloseClipboard(self):
            return 1

    fake_ctypes = MagicMock()
    fake_ctypes.windll.user32 = FakeUser32()
    fake_ctypes.windll.kernel32 = FakeKernel32()
    fake_ctypes.memmove = lambda ptr, data, size: rec.update({"data": data})
    monkeypatch.setitem(__import__("sys").modules, "ctypes", fake_ctypes)

    result = write_clipboard("Jarvis")
    assert "Copied 6 characters" in result
    assert rec["set"][0] == clipboard_mod._CF_UNICODETEXT
    assert rec["data"] == "Jarvis".encode("utf-16-le") + b"\x00\x00"
