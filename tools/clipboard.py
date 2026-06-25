"""tools/clipboard.py — Read and write plain-text clipboard contents."""

from __future__ import annotations

import platform

_NOT_WINDOWS = "Clipboard is Windows only."
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def _windows_guard() -> str | None:
    if platform.system() != "Windows":
        return _NOT_WINDOWS
    return None


def read_clipboard() -> str:
    """Read plain text from the system clipboard."""
    if err := _windows_guard():
        return err

    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if not user32.OpenClipboard(None):
        return "Could not open clipboard."

    try:
        handle = user32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return "Clipboard is empty or has no text."
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return "Could not read clipboard data."
        try:
            text = ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
        return text if text else "Clipboard is empty."
    finally:
        user32.CloseClipboard()


def write_clipboard(text: str) -> str:
    """Write plain text to the system clipboard."""
    if err := _windows_guard():
        return err

    content = text if text is not None else ""
    if not content.strip():
        return "Refused: clipboard text is required."

    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if not user32.OpenClipboard(None):
        return "Could not open clipboard."

    try:
        if not user32.EmptyClipboard():
            return "Could not clear clipboard."

        encoded = content.encode("utf-16-le") + b"\x00\x00"
        h_global = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(encoded))
        if not h_global:
            return "Could not allocate clipboard memory."

        ptr = kernel32.GlobalLock(h_global)
        if not ptr:
            kernel32.GlobalFree(h_global)
            return "Could not lock clipboard memory."

        try:
            ctypes.memmove(ptr, encoded, len(encoded))
        finally:
            kernel32.GlobalUnlock(h_global)

        if not user32.SetClipboardData(_CF_UNICODETEXT, h_global):
            kernel32.GlobalFree(h_global)
            return "Could not set clipboard data."

        return f"Copied {len(content)} characters to clipboard."
    finally:
        user32.CloseClipboard()
