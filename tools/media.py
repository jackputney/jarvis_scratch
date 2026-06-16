"""tools/media.py — Find and open media files on macOS."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

_TIMEOUT = 10

_TYPE_FILTERS = {
    "pdf": "kMDItemContentType == 'com.adobe.pdf'",
    "image": "kMDItemContentTypeTree == 'public.image'",
    "video": "kMDItemContentTypeTree == 'public.movie'",
    "presentation": "kMDItemContentType == 'com.microsoft.powerpoint.ppt'",
    "doc": "kMDItemContentTypeTree == 'public.text'",
}


def _darwin_only(feature: str) -> str | None:
    if platform.system() != "Darwin":
        return f"{feature} is macOS only."
    return None


def open_photos(query: str = "") -> str:
    """Open the Photos app, optionally searching for a query."""
    blocked = _darwin_only("Photos app control")
    if blocked:
        return blocked
    try:
        if query:
            subprocess.run(
                ["osascript", "-e", 'tell application "Photos" to activate'],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
            return f"Opened Photos. Search manually for: {query}"
        subprocess.run(["open", "-a", "Photos"], check=False, timeout=_TIMEOUT)
        return "Opened Photos."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't open Photos: {exc}"


def open_podcasts(query: str = "") -> str:
    """Open the Podcasts app."""
    blocked = _darwin_only("Podcasts app")
    if blocked:
        return blocked
    try:
        subprocess.run(["open", "-a", "Podcasts"], check=False, timeout=_TIMEOUT)
        suffix = f" Look for: {query}" if query else ""
        return f"Opened Podcasts.{suffix}"
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't open Podcasts: {exc}"


def find_file(query: str, file_type: str = "") -> str:
    """Search for files using Spotlight (mdfind). Returns top 5 matches."""
    blocked = _darwin_only("File search")
    if blocked:
        return blocked

    home = str(Path.home())
    ft = (file_type or "").strip().lower()
    if ft and ft in _TYPE_FILTERS:
        expr = f"({_TYPE_FILTERS[ft]}) && kMDItemDisplayName == '*{query}*'c"
        cmd = ["mdfind", "-onlyin", home, expr]
    else:
        cmd = ["mdfind", "-onlyin", home, query]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
        if result.returncode != 0:
            return f"Search failed: {(result.stderr or result.stdout or '').strip()}"
        files = [f for f in result.stdout.strip().split("\n") if f][:5]
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Search failed: {exc}"

    if not files:
        return f"No files found matching '{query}'."

    response = f"Found {len(files)} file(s) matching '{query}':\n"
    response += "\n".join(
        f"  {i + 1}. {os.path.basename(f)} — {f}" for i, f in enumerate(files)
    )
    return response


def open_file(file_path: str) -> str:
    """Open a specific file in its default app."""
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"
    try:
        if platform.system() == "Windows":
            os.startfile(file_path)  # type: ignore[attr-defined]
        else:
            subprocess.run(["open", file_path], check=False, timeout=_TIMEOUT)
        return f"Opened: {os.path.basename(file_path)}"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return f"Couldn't open file: {exc}"


def find_and_open_file(query: str, file_type: str = "") -> str:
    """Find a file by name and open the top match."""
    blocked = _darwin_only("File search")
    if blocked:
        return blocked

    home = str(Path.home())
    ft = (file_type or "").strip().lower()
    if ft and ft in _TYPE_FILTERS:
        expr = f"({_TYPE_FILTERS[ft]}) && kMDItemDisplayName == '*{query}*'c"
        cmd = ["mdfind", "-onlyin", home, expr]
    else:
        cmd = ["mdfind", "-onlyin", home, f"kMDItemDisplayName == '*{query}*'c"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
        if result.returncode != 0:
            return f"Search failed: {(result.stderr or result.stdout or '').strip()}"
        files = [f for f in result.stdout.strip().split("\n") if f]
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Search failed: {exc}"

    if not files:
        return f"No file found matching '{query}'."

    top = files[0]
    return open_file(top)


def open_downloads() -> str:
    """Open the Downloads folder in Finder."""
    downloads = str(Path.home() / "Downloads")
    try:
        if platform.system() == "Windows":
            os.startfile(downloads)  # type: ignore[attr-defined]
        else:
            subprocess.run(["open", downloads], check=False, timeout=_TIMEOUT)
        return "Opened Downloads folder."
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return f"Couldn't open Downloads: {exc}"


def open_desktop() -> str:
    """Open the Desktop folder in Finder."""
    desktop = str(Path.home() / "Desktop")
    try:
        if platform.system() == "Windows":
            os.startfile(desktop)  # type: ignore[attr-defined]
        else:
            subprocess.run(["open", desktop], check=False, timeout=_TIMEOUT)
        return "Opened Desktop."
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return f"Couldn't open Desktop: {exc}"


def get_recent_files(count: int = 10) -> str:
    """Get recently modified files using Spotlight."""
    blocked = _darwin_only("Recent files")
    if blocked:
        return blocked

    try:
        count = max(1, min(int(count), 50))
    except (TypeError, ValueError):
        count = 10

    home = str(Path.home())
    cmd = [
        "mdfind",
        "-onlyin",
        home,
        "kMDItemLastUsedDate >= $time.today(-7)",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
        if result.returncode != 0:
            return f"Search failed: {(result.stderr or result.stdout or '').strip()}"
        files = [f for f in result.stdout.strip().split("\n") if f and "/" in f][:count]
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Search failed: {exc}"

    if not files:
        return "No recent files found."

    return "Recent files:\n" + "\n".join(
        f"  {i + 1}. {os.path.basename(f)}" for i, f in enumerate(files)
    )
