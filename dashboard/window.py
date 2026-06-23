"""dashboard/window.py — Native dashboard window via PyWebView.

Flask keeps serving on 127.0.0.1:7777 (browser fallback). This module opens that
URL in a real desktop window (macOS + Windows). Works in dev and frozen builds.

PyWebView must run on a process main thread. When the PyQt6 orb owns the main
thread, we spawn a dedicated child process for the dashboard window.
"""

from __future__ import annotations

import logging
import multiprocessing
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from paths import dashboard_url, launched_by_launchd

logger = logging.getLogger("jarvis.dashboard.window")

_NATIVE_WINDOW_PLATFORMS = frozenset({"darwin", "win32"})

_window_thread: threading.Thread | None = None
_webview_process: multiprocessing.Process | None = None
_DEFAULT_TIMEOUT_SEC = 30.0
_POLL_INTERVAL_SEC = 0.25


def wait_for_dashboard(timeout: float = _DEFAULT_TIMEOUT_SEC) -> bool:
    """Poll the Flask /api/state endpoint until it responds or timeout."""
    url = dashboard_url("/api/state")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(_POLL_INTERVAL_SEC)
    return False


def _webview_process_main(url: str) -> None:
    """Entry point for the PyWebView child process (owns its own main thread)."""
    try:
        import webview
    except ImportError:
        return

    window = webview.create_window(
        "Jarvis",
        url,
        width=1280,
        height=840,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
        focus=True,
    )
    webview.start(debug=False, private_mode=False)


def _open_in_browser(url: str) -> None:
    """Fallback when PyWebView cannot start (launchd / missing dep)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", url], start_new_session=True)  # noqa: S603
    else:
        import webbrowser

        webbrowser.open(url)


def _start_webview_subprocess(url: str) -> None:
    global _webview_process
    if _webview_process is not None and _webview_process.is_alive():
        return
    try:
        import webview  # noqa: F401
    except ImportError:
        logger.warning(
            "⚠️  pywebview not installed — opening dashboard in your browser: %s",
            url,
        )
        _open_in_browser(url)
        return

    ctx = multiprocessing.get_context("spawn")
    _webview_process = ctx.Process(
        target=_webview_process_main,
        args=(url,),
        daemon=True,
        name="jarvis-dashboard-webview",
    )
    _webview_process.start()
    logger.info("🪟 Native dashboard window opening (%s)", url)


def _run_dashboard_window() -> None:
    if not wait_for_dashboard():
        logger.error("⚠️  Dashboard did not become ready — native window skipped.")
        return

    url = dashboard_url()

    # LaunchAgent sessions are headless-ish — browser is more reliable than PyWebView.
    if launched_by_launchd():
        logger.info("🪟 Launch-at-login — opening dashboard in browser (%s)", url)
        _open_in_browser(url)
        return

    try:
        _start_webview_subprocess(url)
    except Exception as exc:  # noqa: BLE001
        logger.error("⚠️  Native dashboard window failed (%s) — opening browser.", exc)
        _open_in_browser(url)


def start_native_dashboard_window(*, block: bool = False) -> threading.Thread | None:
    """Launch the dashboard in a native PyWebView window (macOS/Windows)."""
    if sys.platform not in _NATIVE_WINDOW_PLATFORMS:
        return None

    global _window_thread
    if _window_thread is not None and _window_thread.is_alive():
        return _window_thread

    if block:
        _run_dashboard_window()
        return None

    _window_thread = threading.Thread(
        target=_run_dashboard_window,
        daemon=True,
        name="jarvis-dashboard-window",
    )
    _window_thread.start()
    return _window_thread


def native_window_supported() -> bool:
    """True when pywebview is importable on this desktop platform."""
    if sys.platform not in _NATIVE_WINDOW_PLATFORMS:
        return False
    try:
        import webview  # noqa: F401

        return True
    except ImportError:
        return False
