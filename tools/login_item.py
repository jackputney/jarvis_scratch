"""tools/login_item.py — macOS LaunchAgent for start Jarvis at login."""

from __future__ import annotations

import logging
import os
import plistlib
import platform
import subprocess
import sys
from pathlib import Path

from paths import (
    LAUNCH_AGENT_LABEL,
    bundle_root,
    is_frozen,
    launch_agent_log_paths,
    launch_agent_plist_path,
    launch_agent_program_arguments,
    launch_agent_working_directory,
)

logger = logging.getLogger("jarvis.login_item")


def _darwin_only() -> bool:
    return platform.system() == "Darwin"


def _gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _run_launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def build_launch_agent_plist() -> dict:
    """Build the LaunchAgent plist payload for the current dev or frozen layout."""
    stdout_log, stderr_log = launch_agent_log_paths()
    payload: dict = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": launch_agent_program_arguments(),
        "RunAtLoad": True,
        "KeepAlive": False,
        "WorkingDirectory": str(launch_agent_working_directory()),
        "StandardOutPath": str(stdout_log),
        "StandardErrorPath": str(stderr_log),
        "ProcessType": "Interactive",
    }
    if not is_frozen():
        venv_bin = bundle_root() / ".venv" / "bin"
        if venv_bin.is_dir():
            payload["EnvironmentVariables"] = {
                "PATH": f"{venv_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                "JARVIS_LAUNCHD": "1",
            }
        else:
            payload["EnvironmentVariables"] = {"JARVIS_LAUNCHD": "1"}
    else:
        payload["EnvironmentVariables"] = {"JARVIS_LAUNCHD": "1"}
    return payload


def write_launch_agent_plist(path: Path | None = None) -> Path:
    """Write ~/Library/LaunchAgents/com.jarvis.app.plist."""
    target = path or launch_agent_plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_launch_agent_plist()
    with target.open("wb") as fh:
        plistlib.dump(payload, fh)
    return target


def is_login_item_enabled() -> bool:
    """True when the LaunchAgent plist is loaded in the user's GUI domain."""
    if not _darwin_only():
        return False
    plist = launch_agent_plist_path()
    if not plist.is_file():
        return False
    result = _run_launchctl("print", f"{_gui_domain()}/{LAUNCH_AGENT_LABEL}")
    return result.returncode == 0


def enable_login_item() -> str:
    """Install and load the LaunchAgent so Jarvis starts at login."""
    if not _darwin_only():
        return "Launch at login is macOS only."

    plist = write_launch_agent_plist()
    domain = _gui_domain()

    # Unload a previous registration before bootstrapping the updated plist.
    _run_launchctl("bootout", domain, str(plist))

    result = _run_launchctl("bootstrap", domain, str(plist))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        logger.error("launchctl bootstrap failed: %s", detail)
        return f"Could not enable launch at login: {detail or 'launchctl bootstrap failed'}"

    mode = "app bundle" if getattr(sys, "frozen", False) else "dev"
    logger.info("✅ Launch at login enabled (%s) → %s", mode, plist)
    return f"Launch at login enabled ({mode}). Jarvis will start automatically when you log in."


def disable_login_item() -> str:
    """Unload and remove the LaunchAgent plist."""
    if not _darwin_only():
        return "Launch at login is macOS only."

    plist = launch_agent_plist_path()
    if plist.is_file():
        _run_launchctl("bootout", _gui_domain(), str(plist))
        plist.unlink()

    logger.info("✅ Launch at login disabled")
    return "Launch at login disabled."
