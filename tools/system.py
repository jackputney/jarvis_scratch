"""
tools/system.py — macOS system-level tools for Jarvis.

Currently provides open_app(), which launches an application by name via AppleScript.
This keeps the tool layer thin: it does exactly one thing and returns a plain result string.
"""

from __future__ import annotations

import subprocess


def open_app(app_name: str) -> str:
    """Open a macOS application by name using AppleScript.

    Args:
        app_name: The name of the application as it appears in /Applications,
                  e.g. "Safari", "Terminal", "Spotify".

    Returns:
        A short plain-text result string describing what happened.
    """
    script = f'tell application "{app_name}" to activate'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return f"Opened {app_name}."
    return f"Failed to open {app_name}: {result.stderr.strip()}"
