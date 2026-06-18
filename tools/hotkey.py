"""tools/hotkey.py — Global hotkey listener for Jarvis.

Registers a configurable key combo system-wide so the user can wake Jarvis
without saying the wake word.  Uses pynput.GlobalHotKeys which works on both
macOS and Windows.

macOS note: the process needs the Accessibility permission the first time it
tries to register a global listener.  macOS will show a system dialog; after
granting it in System Settings → Privacy & Security → Accessibility, restart
Jarvis.

Hotkey format: pynput canonical — e.g. '<ctrl>+<shift>+<space>' or
'<cmd>+<space>'.  Loose aliases like 'ctrl+shift+space' are also accepted
and normalised automatically.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger("jarvis.hotkey")

_listener_thread: threading.Thread | None = None

# Map of loose aliases → pynput canonical tokens.
_ALIASES: dict[str, str] = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "shift": "<shift>",
    "alt": "<alt>",
    "option": "<alt>",
    "cmd": "<cmd>",
    "command": "<cmd>",
    "super": "<cmd>",
    "win": "<cmd>",
    "space": "<space>",
    "esc": "<esc>",
    "escape": "<esc>",
    "tab": "<tab>",
    "enter": "<enter>",
    "return": "<enter>",
    "backspace": "<backspace>",
    "delete": "<delete>",
    **{f"f{n}": f"<f{n}>" for n in range(1, 13)},
}


def normalize_combo(combo: str) -> str:
    """Normalise a loose combo string to pynput canonical format.

    Examples:
        'ctrl+shift+space'  → '<ctrl>+<shift>+<space>'
        '<ctrl>+<shift>+j'  → '<ctrl>+<shift>+j'  (already canonical)
    """
    parts = [p.strip() for p in combo.split("+")]
    out: list[str] = []
    for part in parts:
        lower = part.lower()
        if lower in _ALIASES:
            out.append(_ALIASES[lower])
        else:
            out.append(part)  # already canonical token or bare char
    return "+".join(out)


def start_hotkey_listener(
    combo: str,
    on_trigger: Callable[[], None],
) -> threading.Thread | None:
    """Register a global hotkey and start the background listener thread.

    Returns the daemon thread on success, None if pynput is unavailable.
    """
    global _listener_thread

    try:
        from pynput import keyboard as _kb  # noqa: F401
    except ImportError:
        logger.warning(
            "⚠️  pynput not installed — global hotkey disabled. "
            "Run: pip install pynput"
        )
        return None

    normalized = normalize_combo(combo)

    def _fire() -> None:
        logger.info("⌨️  Global hotkey pressed (%s).", combo)
        try:
            on_trigger()
        except Exception as exc:  # noqa: BLE001
            logger.error("⚠️  Hotkey callback raised: %s", exc)

    def _run() -> None:
        from pynput import keyboard

        try:
            with keyboard.GlobalHotKeys({normalized: _fire}) as listener:
                listener.join()
        except Exception as exc:  # noqa: BLE001
            logger.error("⚠️  Global hotkey listener stopped unexpectedly: %s", exc)

    t = threading.Thread(target=_run, daemon=True, name="jarvis-hotkey")
    t.start()
    _listener_thread = t
    logger.info("⌨️  Global hotkey registered: %s", normalized)
    return t


def stop_hotkey_listener() -> None:
    """Best-effort stop.  The thread is a daemon so it exits with the process."""
    global _listener_thread
    _listener_thread = None
