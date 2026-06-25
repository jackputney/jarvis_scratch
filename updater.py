"""Self-update module for Jarvis on Windows.

Checks for upstream changes on origin/main, applies fast-forward updates,
and signals the launcher to restart the process.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
RESTART_FLAG = REPO_ROOT / ".restart_pending"
GIT_TIMEOUT = 30  # seconds


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )


def check_for_updates() -> dict:
    """Fetch origin/main and compare with local HEAD."""
    fetch = _git("fetch", "origin", "main")
    if fetch.returncode != 0:
        return {"available": False, "local_sha": "", "remote_sha": "",
                "commits_behind": 0, "error": fetch.stderr.strip()}

    local = _git("rev-parse", "HEAD")
    remote = _git("rev-parse", "origin/main")
    local_sha = local.stdout.strip()
    remote_sha = remote.stdout.strip()

    if local_sha == remote_sha:
        return {"available": False, "local_sha": local_sha,
                "remote_sha": remote_sha, "commits_behind": 0}

    count = _git("rev-list", "--count", f"{local_sha}..{remote_sha}")
    behind = int(count.stdout.strip()) if count.returncode == 0 else 0

    return {"available": True, "local_sha": local_sha,
            "remote_sha": remote_sha, "commits_behind": behind}


def apply_update() -> dict:
    """Pull origin/main with fast-forward only. Returns result dict."""
    old = _git("rev-parse", "HEAD")
    old_sha = old.stdout.strip()

    pull = _git("pull", "origin", "main", "--ff-only")
    if pull.returncode != 0:
        return {"success": False, "old_sha": old_sha, "new_sha": old_sha,
                "error": pull.stderr.strip()}

    new = _git("rev-parse", "HEAD")
    new_sha = new.stdout.strip()
    return {"success": True, "old_sha": old_sha, "new_sha": new_sha,
            "error": None}


def restart_jarvis() -> None:
    """Write restart flag and exit so the launcher can restart us."""
    RESTART_FLAG.write_text("1")
    sys.exit(0)


def check_and_prompt_update() -> str:
    """Return a TTS-friendly summary of update status."""
    info = check_for_updates()
    if info.get("error"):
        return f"I couldn't check for updates: {info['error']}"
    if not info["available"]:
        return "You're up to date."
    n = info["commits_behind"]
    word = "commit" if n == 1 else "commits"
    return f"An update is available with {n} new {word}."
