"""tools/media_control.py — Windows global media keys (play/pause/skip/previous)."""

from __future__ import annotations

import platform

_NOT_WINDOWS = "Media control is Windows only."

VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002


def _windows_guard() -> str | None:
    if platform.system() != "Windows":
        return _NOT_WINDOWS
    return None


def _send_media_key(vk_code: int) -> None:
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUT)]

    extra = ctypes.c_ulong(0)
    inputs = (INPUT * 2)()
    for idx, flags in enumerate((0, KEYEVENTF_KEYUP)):
        inputs[idx].type = INPUT_KEYBOARD
        inputs[idx].ki = KEYBDINPUT(vk_code, 0, flags, 0, ctypes.pointer(extra))

    sent = ctypes.windll.user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
    if sent != 2:
        raise OSError(f"SendInput returned {sent}")


def media_control(action: str) -> str:
    """Send a global media key to the app with media focus (Spotify, browser, etc.)."""
    if err := _windows_guard():
        return err

    act = (action or "").strip().lower()
    key_map = {
        "play": VK_MEDIA_PLAY_PAUSE,
        "pause": VK_MEDIA_PLAY_PAUSE,
        "play_pause": VK_MEDIA_PLAY_PAUSE,
        "skip": VK_MEDIA_NEXT_TRACK,
        "next": VK_MEDIA_NEXT_TRACK,
        "previous": VK_MEDIA_PREV_TRACK,
        "prev": VK_MEDIA_PREV_TRACK,
    }
    vk = key_map.get(act)
    if vk is None:
        return (
            f"Refused: action must be one of play, pause, play_pause, skip, next, "
            f"previous, or prev, not {action!r}."
        )

    try:
        _send_media_key(vk)
    except OSError as exc:
        return f"Media control error: {exc}"

    labels = {
        VK_MEDIA_PLAY_PAUSE: "play/pause",
        VK_MEDIA_NEXT_TRACK: "skip",
        VK_MEDIA_PREV_TRACK: "previous",
    }
    return f"Sent media key: {labels[vk]}."
