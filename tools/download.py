"""
tools/download.py — Download a file from the web to the user's Downloads folder.

Confirm-required (see registry CONFIRM_REQUIRED_TOOLS). Validates the URL,
streams the body with a hard size cap so a runaway download can't fill the disk,
and never overwrites an existing file (auto-suffixes "name (1).ext"). Saves to
~/Downloads on every platform (Path.home() resolves correctly on Windows + macOS
+ Linux).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

REQUEST_TIMEOUT = 30
MAX_BYTES = 100 * 1024 * 1024  # 100 MB hard cap
CHUNK_SIZE = 64 * 1024
_FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)
_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _downloads_dir() -> Path:
    d = Path.home() / "Downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitise(name: str) -> str:
    """Strip path separators and unsafe characters; keep it a bare filename."""
    name = unquote(name).strip().replace("\n", " ")
    name = _UNSAFE_RE.sub("_", name).strip(". ")
    return name[:200] or "download"


def _name_from_headers(resp, url: str) -> str:
    disp = resp.headers.get("Content-Disposition", "")
    match = _FILENAME_RE.search(disp)
    if match:
        return _sanitise(match.group(1))
    path_name = Path(urlparse(url).path).name
    return _sanitise(path_name) if path_name else "download"


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    n = 1
    while True:
        candidate = directory / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def download_file(url: str, filename: str | None = None) -> str:
    """Download `url` to ~/Downloads, returning a human-readable result line."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return f"Download refused: '{url}' is not a valid http(s) URL."

    try:
        import requests
    except ImportError as exc:
        return f"Download failed: {exc}"

    try:
        with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()

            declared = resp.headers.get("Content-Length")
            if declared is not None and declared.isdigit() and int(declared) > MAX_BYTES:
                return (
                    f"Download refused: file is {_human(int(declared))}, "
                    f"over the {_human(MAX_BYTES)} limit."
                )

            name = _sanitise(filename) if filename else _name_from_headers(resp, url)
            dest = _unique_path(_downloads_dir(), name)

            written = 0
            try:
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > MAX_BYTES:
                            fh.close()
                            dest.unlink(missing_ok=True)
                            return (
                                f"Download aborted: exceeded the {_human(MAX_BYTES)} "
                                f"limit partway through."
                            )
                        fh.write(chunk)
            except Exception:
                dest.unlink(missing_ok=True)
                raise
    except Exception as exc:  # noqa: BLE001
        return f"Download failed: {exc}"

    return f"Downloaded {dest.name} ({_human(written)}) to {dest.parent}."
