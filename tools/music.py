"""tools/music.py — Music playback control (macOS Music.app + Windows Spotify stub)."""

from __future__ import annotations

import platform
import subprocess
import urllib.parse

_OSASCRIPT_TIMEOUT = 15
_NOT_MAC = "Music control is macOS only."
_NOT_WINDOWS = "Music control is not supported on Windows."


def _escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run_applescript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=_OSASCRIPT_TIMEOUT,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "AppleScript failed").strip()
        return f"Music error: {detail.splitlines()[0]}"
    return (result.stdout or "").strip() or "Done."


def _darwin_guard() -> str | None:
    if platform.system() != "Darwin":
        return _NOT_MAC
    return None


def play() -> str:
    """Start or resume playback in Music.app."""
    if err := _darwin_guard():
        return err
    return _run_applescript('tell application "Music" to play')


def pause() -> str:
    """Pause playback in Music.app."""
    if err := _darwin_guard():
        return err
    return _run_applescript('tell application "Music" to pause')


def skip() -> str:
    """Skip to the next track in Music.app."""
    if err := _darwin_guard():
        return err
    return _run_applescript('tell application "Music" to next track')


def previous() -> str:
    """Go to the previous track in Music.app."""
    if err := _darwin_guard():
        return err
    return _run_applescript('tell application "Music" to previous track')


def set_volume(level: int) -> str:
    """Set Music.app playback volume (0–100). Not system master volume."""
    if err := _darwin_guard():
        return err
    clamped = max(0, min(100, int(level)))
    return _run_applescript(f'tell application "Music" to set sound volume to {clamped}')


def get_now_playing() -> str:
    """Return the current track name, artist, album, and player state."""
    if platform.system() == "Darwin":
        script = """
tell application "Music"
  set pState to player state as string
  if pState is not "playing" then
    if pState is "paused" then
      try
        set t to current track
        return "Paused: " & (name of t) & " — " & (artist of t)
      on error
        return "Paused."
      end try
    end if
    return "Not playing."
  end if
  set t to current track
  return (name of t) & " — " & (artist of t) & " · " & (album of t)
end tell
"""
        return _run_applescript(script)
    if platform.system() == "Windows":
        return _NOT_WINDOWS
    return _NOT_MAC


def search_and_play(query: str) -> str:
    """Search the library and play the top match (macOS) or open Spotify search (Windows)."""
    q = (query or "").strip()
    if not q:
        return "Refused: search query is required."

    if platform.system() == "Darwin":
        safe = _escape_applescript(q)
        script = f"""
tell application "Music"
  set foundTracks to (search library playlist 1 for "{safe}" only songs)
  if (count of foundTracks) is 0 then
    return "No songs found matching '{safe}'."
  end if
  set t to item 1 of foundTracks
  play t
  return "Playing: " & (name of t) & " — " & (artist of t)
end tell
"""
        return _run_applescript(script)

    if platform.system() == "Windows":
        uri = f"spotify:search:{urllib.parse.quote(q)}"
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", "Start-Process", uri],
            )
            return (
                f"Opened Spotify search for '{q}'. "
                "I can't control playback on Windows yet — use Spotify directly to play."
            )
        except Exception as exc:  # noqa: BLE001
            return f"Could not open Spotify: {exc}"

    return _NOT_MAC
