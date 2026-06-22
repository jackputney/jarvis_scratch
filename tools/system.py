"""
tools/system.py — Cross-platform system-level tools for Jarvis.

Provides open_app(), which launches an application by name using the native
launcher on macOS, Windows, or Linux.
"""

from __future__ import annotations

import platform
import re
import subprocess

# Letters, numbers, spaces, dots, hyphens — typical application names only.
_APP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .\-]{0,63}$")

# Back-compat alias used in security tests / docs.
SAFE_APP_NAME = _APP_NAME_RE


def validate_app_name(app_name: str) -> str | None:
    """Return a sanitised app name or None if invalid."""
    name = (app_name or "").strip()
    if not name or not _APP_NAME_RE.fullmatch(name):
        return None
    return name


def open_app(app_name: str) -> str:
    """Open an application by name on the current platform.

    Args:
        app_name: Application name as shown in the launcher (e.g. "Safari", "Notepad").

    Returns:
        A short plain-text result string describing what happened.
    """
    safe_name = validate_app_name(app_name)
    if not safe_name:
        return (
            f"Refused to open {app_name!r}: invalid application name. "
            "Use letters, numbers, spaces, dots, or hyphens only."
        )

    system = platform.system()
    try:
        if system == "Darwin":
            cmd = ["open", "-a", safe_name]
        elif system == "Windows":
            cmd = ["powershell", "-NoProfile", "-Command", "Start-Process", safe_name]
        else:
            cmd = ["xdg-open", safe_name]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return f"Opened {safe_name}."
        err = (result.stderr or result.stdout or "unknown error").strip()
        return f"Failed to open {safe_name}: {err}"
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return f"Could not open '{safe_name}'."
