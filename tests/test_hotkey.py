"""tests/test_hotkey.py — Global hotkey listener tests.

Tests cover:
  - Combo normalisation (loose → pynput canonical)
  - request_wake() sets _hotkey_pending
  - request_wake() calls request_interrupt() when pipeline is mid-turn
  - Config fields exist with correct defaults
  - start_hotkey_listener() handles missing pynput gracefully
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# normalize_combo
# ---------------------------------------------------------------------------


def test_normalize_ctrl_shift_space():
    from tools.hotkey import normalize_combo

    assert normalize_combo("ctrl+shift+space") == "<ctrl>+<shift>+<space>"


def test_normalize_already_canonical():
    from tools.hotkey import normalize_combo

    result = normalize_combo("<ctrl>+<shift>+<space>")
    assert result == "<ctrl>+<shift>+<space>"


def test_normalize_cmd_alias():
    from tools.hotkey import normalize_combo

    assert normalize_combo("cmd+space") == "<cmd>+<space>"


def test_normalize_option_alias():
    from tools.hotkey import normalize_combo

    assert normalize_combo("option+f5") == "<alt>+<f5>"


def test_normalize_single_char_key():
    from tools.hotkey import normalize_combo

    assert normalize_combo("ctrl+shift+j") == "<ctrl>+<shift>+j"


def test_normalize_function_keys():
    from tools.hotkey import normalize_combo

    for n in range(1, 13):
        result = normalize_combo(f"ctrl+f{n}")
        assert result == f"<ctrl>+<f{n}>", f"f{n} not normalised correctly"


# ---------------------------------------------------------------------------
# request_wake()
# ---------------------------------------------------------------------------


def test_request_wake_sets_hotkey_pending():
    import pipeline

    pipeline._hotkey_pending.clear()
    with patch.object(pipeline.events, "get_state", return_value={"pipeline_state": "IDLE"}):
        pipeline.request_wake()

    assert pipeline._hotkey_pending.is_set()


def test_request_wake_does_not_interrupt_when_idle():
    import pipeline

    pipeline._hotkey_pending.clear()
    with patch.object(pipeline.events, "get_state", return_value={"pipeline_state": "IDLE"}), \
         patch.object(pipeline, "request_interrupt") as mock_interrupt:
        pipeline.request_wake()

    mock_interrupt.assert_not_called()
    assert pipeline._hotkey_pending.is_set()


def test_request_wake_interrupts_when_thinking():
    import pipeline

    pipeline._hotkey_pending.clear()
    with patch.object(pipeline.events, "get_state", return_value={"pipeline_state": "THINKING"}), \
         patch.object(pipeline, "request_interrupt") as mock_interrupt:
        pipeline.request_wake()

    mock_interrupt.assert_called_once()
    assert pipeline._hotkey_pending.is_set()


def test_request_wake_interrupts_when_speaking():
    import pipeline

    pipeline._hotkey_pending.clear()
    with patch.object(pipeline.events, "get_state", return_value={"pipeline_state": "SPEAKING"}), \
         patch.object(pipeline, "request_interrupt") as mock_interrupt:
        pipeline.request_wake()

    mock_interrupt.assert_called_once()


def test_request_wake_is_thread_safe():
    """Multiple threads calling request_wake() must not raise."""
    import pipeline

    pipeline._hotkey_pending.clear()
    errors: list[Exception] = []

    def _call():
        try:
            with patch.object(
                pipeline.events, "get_state", return_value={"pipeline_state": "IDLE"}
            ):
                pipeline.request_wake()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_call) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert pipeline._hotkey_pending.is_set()


# ---------------------------------------------------------------------------
# Config fields
# ---------------------------------------------------------------------------


def test_hotkey_enabled_default():
    from config import Config

    assert Config().hotkey_enabled is True


def test_hotkey_combo_default():
    from config import Config

    assert Config().hotkey_combo == "<ctrl>+<shift>+<space>"


def test_hotkey_combo_in_persisted_fields():
    from config import _PERSISTED_FIELDS

    assert "hotkey_combo" in _PERSISTED_FIELDS
    assert "hotkey_enabled" in _PERSISTED_FIELDS


# ---------------------------------------------------------------------------
# start_hotkey_listener — import guard
# ---------------------------------------------------------------------------


def test_start_hotkey_listener_returns_none_without_pynput():
    with patch.dict("sys.modules", {"pynput": None, "pynput.keyboard": None}):
        from tools import hotkey
        import importlib

        importlib.reload(hotkey)
        result = hotkey.start_hotkey_listener("ctrl+shift+space", lambda: None)
        assert result is None


def test_start_hotkey_listener_starts_daemon_thread(monkeypatch):
    """When pynput is available, a daemon thread is started and returned."""
    mock_listener = MagicMock()
    mock_listener.__enter__ = MagicMock(return_value=mock_listener)
    mock_listener.__exit__ = MagicMock(return_value=False)
    mock_listener.join = MagicMock()  # prevent it from blocking

    mock_keyboard = MagicMock()
    mock_keyboard.GlobalHotKeys.return_value = mock_listener

    from tools import hotkey

    with patch.dict("sys.modules", {"pynput": MagicMock(), "pynput.keyboard": mock_keyboard}):
        callback = MagicMock()
        t = hotkey.start_hotkey_listener("<ctrl>+<shift>+<space>", callback)

    # A thread should have been returned (it may have already finished if mock join
    # returned immediately, but the object itself should be a Thread).
    assert t is not None
    assert isinstance(t, threading.Thread)
    assert t.daemon


def test_stop_hotkey_listener_calls_stop_on_listener():
    """Regression: stop_hotkey_listener previously only nulled the thread ref.
    Now it calls .stop() on the active pynput listener instance."""
    import tools.hotkey as hotkey_mod

    mock_listener = MagicMock()
    hotkey_mod._active_listener = mock_listener
    hotkey_mod._listener_thread = threading.Thread(target=lambda: None, daemon=True)

    hotkey_mod.stop_hotkey_listener()

    mock_listener.stop.assert_called_once()
    assert hotkey_mod._active_listener is None
    assert hotkey_mod._listener_thread is None


def test_stop_hotkey_listener_safe_when_no_active_listener():
    """stop_hotkey_listener must not raise when called without a running listener."""
    import tools.hotkey as hotkey_mod

    hotkey_mod._active_listener = None
    hotkey_mod._listener_thread = None

    # Should not raise
    hotkey_mod.stop_hotkey_listener()
