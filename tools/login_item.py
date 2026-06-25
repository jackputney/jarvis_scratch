"""tools/login_item.py — Launch at login (macOS LaunchAgent + Windows Task Scheduler)."""

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

_WINDOWS_TASK_NAME = "Jarvis"


def _darwin_only() -> bool:
    return platform.system() == "Darwin"


def _windows_only() -> bool:
    return platform.system() == "Windows"


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


def _run_schtasks(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _windows_task_tr() -> str:
    """Task Scheduler /TR argument for starting Jarvis at logon."""
    if is_frozen():
        return f'"{Path(sys.executable).resolve()}"'
    run_ps1 = (bundle_root() / "run.ps1").resolve()
    return (
        f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{run_ps1}"'
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


def _is_windows_startup_enabled() -> bool:
    result = _run_schtasks("/Query", "/TN", _WINDOWS_TASK_NAME)
    return result.returncode == 0


def _enable_windows_startup() -> str:
    tr = _windows_task_tr()
    result = _run_schtasks(
        "/Create",
        "/TN",
        _WINDOWS_TASK_NAME,
        "/TR",
        tr,
        "/SC",
        "ONLOGON",
        "/RL",
        "LIMITED",
        "/F",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        logger.error("schtasks create failed: %s", detail)
        return f"Could not enable launch at login: {detail or 'schtasks create failed'}"

    mode = "app bundle" if is_frozen() else "dev"
    logger.info("✅ Launch at login enabled (%s) → task %s", mode, _WINDOWS_TASK_NAME)
    return f"Launch at login enabled ({mode}). Jarvis will start automatically when you log in."


def _disable_windows_startup() -> str:
    if _is_windows_startup_enabled():
        result = _run_schtasks("/Delete", "/TN", _WINDOWS_TASK_NAME, "/F")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            logger.error("schtasks delete failed: %s", detail)
            return f"Could not disable launch at login: {detail or 'schtasks delete failed'}"

    logger.info("✅ Launch at login disabled")
    return "Launch at login disabled."


def _startup_status() -> str:
    if _darwin_only():
        enabled = is_login_item_enabled()
        mode = "frozen" if is_frozen() else "dev"
        state = "enabled" if enabled else "disabled"
        return f"Launch at login is {state} ({mode}, macOS LaunchAgent)."
    if _windows_only():
        enabled = _is_windows_startup_enabled()
        mode = "frozen" if is_frozen() else "dev"
        state = "enabled" if enabled else "disabled"
        return f"Launch at login is {state} ({mode}, Windows Task Scheduler)."
    return "Launch at login is not supported on this platform."


def is_login_item_enabled() -> bool:
    """True when Jarvis is registered to start at login."""
    if _darwin_only():
        plist = launch_agent_plist_path()
        if not plist.is_file():
            return False
        result = _run_launchctl("print", f"{_gui_domain()}/{LAUNCH_AGENT_LABEL}")
        return result.returncode == 0
    if _windows_only():
        return _is_windows_startup_enabled()
    return False


def enable_login_item() -> str:
    """Install and load the login item so Jarvis starts at login."""
    if _darwin_only():
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

    if _windows_only():
        return _enable_windows_startup()

    return "Launch at login is not supported on this platform."


def disable_login_item() -> str:
    """Remove the login item registration."""
    if _darwin_only():
        plist = launch_agent_plist_path()
        if plist.is_file():
            _run_launchctl("bootout", _gui_domain(), str(plist))
            plist.unlink()

        logger.info("✅ Launch at login disabled")
        return "Launch at login disabled."

    if _windows_only():
        return _disable_windows_startup()

    return "Launch at login is not supported on this platform."


def manage_startup(action: str) -> str:
    """Enable, disable, or check launch-at-login status (macOS or Windows)."""
    act = (action or "").strip().lower()
    if act == "enable":
        return enable_login_item()
    if act == "disable":
        return disable_login_item()
    if act == "status":
        return _startup_status()
    return f"Refused: action must be 'enable', 'disable', or 'status', not {action!r}."
