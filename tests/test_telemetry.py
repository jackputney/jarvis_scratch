"""Tests for the local crash/error telemetry module."""

from __future__ import annotations

import sys
import threading

import pytest


@pytest.fixture(autouse=True)
def _fresh_telemetry(temp_env, monkeypatch):
    """Reset telemetry state for every test so each starts clean."""
    import telemetry

    telemetry.reset_for_tests()
    yield


# ── install_crash_handler ────────────────────────────────────────────


def test_install_sets_excepthook():
    import telemetry

    old = sys.excepthook
    telemetry.install_crash_handler()
    assert sys.excepthook is not old


def test_sys_excepthook_logs_to_db():
    import telemetry

    telemetry.install_crash_handler()
    # Trigger the hook manually (don't let it propagate to stderr).
    try:
        raise ValueError("boom")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    errors = telemetry.get_recent_errors(limit=5)
    assert len(errors) == 1
    assert errors[0]["category"] == "ValueError"
    assert "boom" in errors[0]["message"]
    assert errors[0]["thread_name"] == "MainThread"
    assert errors[0]["traceback_text"] is not None


def test_threading_excepthook_logs_to_db():
    import telemetry

    telemetry.install_crash_handler()

    def _crash():
        raise RuntimeError("thread went bad")

    t = threading.Thread(target=_crash, name="CrashThread")
    t.start()
    t.join(timeout=5)

    errors = telemetry.get_recent_errors(limit=5)
    assert any(
        e["category"] == "RuntimeError" and "thread went bad" in e["message"]
        for e in errors
    )
    crash = [e for e in errors if e["category"] == "RuntimeError"][0]
    assert crash["thread_name"] == "CrashThread"


def test_install_is_idempotent():
    import telemetry

    telemetry.install_crash_handler()
    hook1 = sys.excepthook
    telemetry.install_crash_handler()
    assert sys.excepthook is hook1


# ── log_error ────────────────────────────────────────────────────────


def test_log_error_basic():
    import telemetry

    telemetry.log_error("STT", "mic disconnected")
    errors = telemetry.get_recent_errors()
    assert len(errors) == 1
    assert errors[0]["category"] == "STT"
    assert errors[0]["message"] == "mic disconnected"


def test_log_error_with_extra():
    import telemetry

    telemetry.log_error("TTS", "timeout", extra={"engine": "cartesia", "ms": 5200})
    errors = telemetry.get_recent_errors()
    assert errors[0]["extra_json"] is not None
    import json

    data = json.loads(errors[0]["extra_json"])
    assert data["engine"] == "cartesia"
    assert data["ms"] == 5200


def test_log_error_truncates_long_message():
    import telemetry

    telemetry.log_error("SPAM", "x" * 5000)
    errors = telemetry.get_recent_errors()
    assert len(errors[0]["message"]) <= 2000


# ── get_recent_errors ────────────────────────────────────────────────


def test_get_recent_errors_respects_limit():
    import telemetry

    for i in range(10):
        telemetry.log_error("TEST", f"error {i}")
    assert len(telemetry.get_recent_errors(limit=3)) == 3


def test_get_recent_errors_order():
    import telemetry

    telemetry.log_error("A", "first")
    telemetry.log_error("B", "second")
    errors = telemetry.get_recent_errors()
    assert errors[0]["category"] == "B"  # most recent first
    assert errors[1]["category"] == "A"


def test_get_recent_errors_empty():
    import telemetry

    assert telemetry.get_recent_errors() == []


# ── get_error_summary ────────────────────────────────────────────────


def test_error_summary_groups_by_category():
    import telemetry

    telemetry.log_error("STT", "err1")
    telemetry.log_error("STT", "err2")
    telemetry.log_error("TTS", "err3")
    summary = telemetry.get_error_summary(hours=1)
    by_cat = {row["category"]: row["count"] for row in summary}
    assert by_cat["STT"] == 2
    assert by_cat["TTS"] == 1


def test_error_summary_empty():
    import telemetry

    assert telemetry.get_error_summary() == []
