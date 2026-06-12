"""Dashboard confirm queue — timeout, respond, and Stop cancel."""

import threading
import time

from tools import confirm as tool_confirm


def test_get_pending_none_when_idle():
    assert tool_confirm.get_pending() is None


def test_respond_allow_unblocks_wait():
    result_holder: list[str] = []

    def waiter() -> None:
        result_holder.append(
            tool_confirm.wait_for_confirm("send_email", {"to": "a@b.com"}, timeout_sec=5)
        )

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    for _ in range(40):
        pending = tool_confirm.get_pending()
        if pending is not None:
            tool_confirm.respond(pending["id"], True)
            break
        time.sleep(0.05)
    t.join(timeout=2)
    assert result_holder == ["allow"]


def test_respond_deny():
    result_holder: list[str] = []

    def waiter() -> None:
        result_holder.append(
            tool_confirm.wait_for_confirm("append_row", {"values": ["x"]}, timeout_sec=5)
        )

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    for _ in range(40):
        pending = tool_confirm.get_pending()
        if pending is not None:
            tool_confirm.respond(pending["id"], False)
            break
        time.sleep(0.05)
    t.join(timeout=2)
    assert result_holder == ["deny"]


def test_timeout_auto_denies():
    result = tool_confirm.wait_for_confirm("update_cell", {"cell": "A1"}, timeout_sec=1)
    assert result == "timeout"
    assert tool_confirm.get_pending() is None


def test_cancel_pending_returns_cancel():
    result_holder: list[str] = []

    def waiter() -> None:
        result_holder.append(
            tool_confirm.wait_for_confirm("send_email", {"to": "x@y.com"}, timeout_sec=30)
        )

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    for _ in range(40):
        if tool_confirm.get_pending() is not None:
            tool_confirm.cancel_pending()
            break
        time.sleep(0.05)
    t.join(timeout=2)
    assert result_holder == ["cancel"]


def test_pending_snapshot_shape():
    done = threading.Event()

    def waiter() -> None:
        tool_confirm.wait_for_confirm("send_email", {"to": "a@b.com", "subject": "s"}, timeout_sec=5)
        done.set()

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    pending = None
    for _ in range(40):
        pending = tool_confirm.get_pending()
        if pending is not None:
            break
        time.sleep(0.05)
    assert pending is not None
    assert pending["tool"] == "send_email"
    assert pending["inputs"]["to"] == "a@b.com"
    assert "timeout_sec" in pending
    assert "age_sec" in pending
    tool_confirm.respond(pending["id"], False)
    t.join(timeout=2)
    done.wait(timeout=1)
