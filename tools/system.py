"""
tools/system.py — Cross-platform system-level tools for Jarvis.

Provides open_app(), which launches an application by name using the native
launcher on macOS, Windows, or Linux.
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

# Letters, numbers, spaces, dots, hyphens — typical application names only.
_APP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .\-]{0,63}$")

# Back-compat alias used in security tests / docs.
SAFE_APP_NAME = _APP_NAME_RE

_LOOKUP_TTL_SEC = 600.0
_lookup_cache: dict[str, tuple[str, str] | None] = {}
_lookup_cache_ts: dict[str, float] = {}
_lookup_lock = threading.Lock()

_COMMON_WINDOWS_APPS = (
    "Spotify",
    "Discord",
    "Chrome",
    "Notepad",
    "Microsoft Edge",
    "Cursor",
    "Outlook",
    "Teams",
    "PowerPoint",
    "Word",
    "Excel",
)


def validate_app_name(app_name: str) -> str | None:
    """Return a sanitised app name or None if invalid."""
    name = (app_name or "").strip()
    if not name or not _APP_NAME_RE.fullmatch(name):
        return None
    return name


def _lookup_windows_start_app(safe_name: str) -> tuple[str, str] | None:
    """Resolve a Start-menu app via a filtered PowerShell query (fast, no full scan)."""
    now = time.time()
    with _lookup_lock:
        if safe_name in _lookup_cache and now - _lookup_cache_ts.get(safe_name, 0) < _LOOKUP_TTL_SEC:
            return _lookup_cache[safe_name]

    escaped = safe_name.replace("'", "''")
    ps = f"""
$q = '{escaped}'
$best = $null
$bestScore = -1
Get-StartApps | Where-Object {{ $_.Name -ieq $q -or $_.Name -ilike "*$q*" }} | ForEach-Object {{
    $n = $_.Name
    $score = if ($n -ieq $q) {{ 100 }}
             elseif ($n.ToLower().StartsWith($q.ToLower())) {{ 80 }}
             elseif ($n -ilike "*$q*") {{ 60 }}
             else {{ 0 }}
    if ($score -gt $bestScore) {{ $bestScore = $score; $best = $_ }}
}}
if ($best) {{ Write-Output ($best.Name + '|' + $best.AppID) }}
"""
    match: tuple[str, str] | None = None
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=20,
        )
        line = (result.stdout or "").strip().splitlines()
        if line and "|" in line[0]:
            name, app_id = line[0].split("|", 1)
            if name.strip() and app_id.strip():
                match = (name.strip(), app_id.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("⚠️  Windows Start-menu lookup failed for %r: %s", safe_name, exc)

    with _lookup_lock:
        _lookup_cache[safe_name] = match
        _lookup_cache_ts[safe_name] = time.time()
    return match


def warm_windows_start_apps() -> None:
    """Pre-resolve common apps so first open_app calls are instant."""
    if platform.system() != "Windows":
        return

    def _warm() -> None:
        for app in _COMMON_WINDOWS_APPS:
            _lookup_windows_start_app(app)

    threading.Thread(target=_warm, daemon=True, name="jarvis-startapps").start()


def _launch_windows_app_id(app_id: str) -> bool:
    result = subprocess.run(
        ["cmd", "/c", "start", "", f"shell:AppsFolder\\{app_id}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


def _open_windows_app(safe_name: str) -> tuple[bool, str]:
    """Launch an installed Windows app by Start-menu name."""
    match = _find_windows_start_app(safe_name)
    if match:
        display_name, app_id = match
        if _launch_windows_app_id(app_id):
            return True, display_name

    for cmd in (
        ["cmd", "/c", "start", "", safe_name],
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Start-Process '{safe_name.replace(chr(39), chr(39) * 2)}'",
        ],
    ):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0:
            return True, safe_name

    if match:
        return False, f"No launch method worked for {match[0]!r}."
    return False, f"No installed app matching {safe_name!r} was found in the Start menu."


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
            ok, detail = _open_windows_app(safe_name)
            if ok:
                label = detail if detail != safe_name else safe_name
                return f"Opened {label}."
            return f"Failed to open {safe_name}: {detail}"
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


# Back-compat for tests that monkeypatch the old helper name.
_find_windows_start_app = _lookup_windows_start_app
