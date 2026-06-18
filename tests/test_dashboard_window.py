"""tests/test_dashboard_window.py — Native PyWebView dashboard window."""

from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock, patch


def test_dashboard_url_default():
    from paths import dashboard_url

    assert dashboard_url() == "http://127.0.0.1:7777"
    assert dashboard_url("/api/state") == "http://127.0.0.1:7777/api/state"


def test_dashboard_native_window_config_default():
    from config import Config

    assert Config().dashboard_native_window is True


def test_dashboard_native_window_persisted():
    from config import _PERSISTED_FIELDS

    assert "dashboard_native_window" in _PERSISTED_FIELDS


def test_wait_for_dashboard_returns_true_when_up():
    from dashboard import window as dw

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert dw.wait_for_dashboard(timeout=1.0) is True


def test_wait_for_dashboard_times_out():
    from dashboard import window as dw

    with patch("urllib.request.urlopen", side_effect=OSError("refused")):
        assert dw.wait_for_dashboard(timeout=0.3) is False


def test_start_native_dashboard_window_skips_non_macos():
    from dashboard import window as dw

    with patch("sys.platform", "win32"):
        assert dw.start_native_dashboard_window() is None


@patch.object(sys, "platform", "darwin")
def test_start_native_dashboard_window_starts_thread():
    from dashboard import window as dw

    dw._window_thread = None

    with patch.object(dw, "_run_dashboard_window"):
        t = dw.start_native_dashboard_window()
        assert t is not None
        assert isinstance(t, threading.Thread)
        t.join(timeout=2.0)
        dw._window_thread = None


@patch.object(sys, "platform", "darwin")
def test_run_dashboard_window_spawns_subprocess():
    from dashboard import window as dw

    with patch.object(dw, "wait_for_dashboard", return_value=True), \
         patch.object(dw, "launched_by_launchd", return_value=False), \
         patch.object(dw, "_start_webview_subprocess") as mock_spawn:
        dw._run_dashboard_window()
    mock_spawn.assert_called_once_with("http://127.0.0.1:7777")


@patch.object(sys, "platform", "darwin")
def test_run_dashboard_window_launchd_opens_browser():
    from dashboard import window as dw

    with patch.object(dw, "wait_for_dashboard", return_value=True), \
         patch.object(dw, "launched_by_launchd", return_value=True), \
         patch.object(dw, "_open_in_browser") as mock_open:
        dw._run_dashboard_window()
    mock_open.assert_called_once_with("http://127.0.0.1:7777")


@patch.object(sys, "platform", "darwin")
def test_run_dashboard_window_skips_when_not_ready():
    from dashboard import window as dw

    with patch.object(dw, "wait_for_dashboard", return_value=False), \
         patch.object(dw, "_start_webview_subprocess") as mock_spawn:
        dw._run_dashboard_window()
    mock_spawn.assert_not_called()


def test_native_window_supported_false_without_pywebview():
    from dashboard import window as dw

    with patch.dict(sys.modules, {"webview": None}):
        assert dw.native_window_supported() is False


def test_launched_by_launchd_env():
    from paths import launched_by_launchd

    with patch.dict("os.environ", {"JARVIS_LAUNCHD": "1"}, clear=False):
        assert launched_by_launchd() is True
