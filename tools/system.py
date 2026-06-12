"""
tools/system.py — macOS system-level tools for Jarvis.

Currently provides open_app(), which launches an application by name via the
`open -a` CLI (no AppleScript string interpolation).
"""

from __future__ import annotations

import re
import subprocess
import sys

# Letters, numbers, spaces, dots, hyphens — typical /Applications names only.
_APP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .\-]{0,63}$")


def validate_app_name(app_name: str) -> str | None:
    """Return a sanitised app name or None if invalid."""
    name = (app_name or "").strip()
    if not name or not _APP_NAME_RE.fullmatch(name):
        return None
    return name


def open_app(app_name: str) -> str:
    """Open a macOS application by name.

    Args:
        app_name: The name of the application as it appears in /Applications,
                  e.g. "Safari", "Terminal", "Spotify".

    Returns:
        A short plain-text result string describing what happened.
    """
    safe_name = validate_app_name(app_name)
    if not safe_name:
        return (
            f"Refused to open {app_name!r}: invalid application name. "
            "Use letters, numbers, spaces, dots, or hyphens only."
        )

    if sys.platform != "darwin":
        return "open_app is only supported on macOS."

    result = subprocess.run(
        ["open", "-a", safe_name],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return f"Opened {safe_name}."
    err = (result.stderr or result.stdout or "unknown error").strip()
    return f"Failed to open {safe_name}: {err}"
