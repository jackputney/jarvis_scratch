"""TurnTrace instrumentation tests."""

from __future__ import annotations

import threading
import time
import uuid

import pytest

import sqlite3

from improvement.trace import (
    TurnTrace,
    ensure_session,
    flush_writes,
    record_tool_call,
    reset_writer_for_tests,
)
from memory.db import connect, init_db


@pytest.fixture(autouse=True)
def _trace_writer(temp_env):
    reset_writer_for_tests()
    init_db()
    yield
    flush_writes()
    reset_writer_for_tests()


def _turn_row(turn_id: str) -> dict | None:
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM turns WHERE turn_id = ?", (turn_id,)).fetchone()
    return dict(row) if row else None


def test_turn_trace_writes_complete_row():
    sid = ensure_session(model="claude-haiku-4-5")
    tid = str(uuid.uuid4())
    with TurnTrace(session_id=sid, source="voice", turn_id=tid) as t:
        t.stt_text = "hello world"
        t.stt_confidence = 0.91
        t.stt_ms = 120
        t.llm_ms = 800
        t.tool_ms = 50
        t.tts_ms = 300
        t.model = "claude-haiku-4-5"
        t.tokens_in = 100
        t.tokens_out = 40
    flush_writes()
    row = _turn_row(tid)
    assert row is not None
    assert row["stt_text"] == "hello world"
    assert row["stt_confidence"] == pytest.approx(0.91)
    assert row["total_ms"] is not None


def test_record_tool_call_writes_tool_call_event():
    sid = ensure_session()
    tid = str(uuid.uuid4())
    with TurnTrace(session_id=sid, source="dashboard", turn_id=tid):
        record_tool_call(tid, "get_time", {}, "12:00", 12)
    flush_writes()
    with connect() as conn:
        row = conn.execute(
            "SELECT type FROM events WHERE turn_id = ?", (tid,)
        ).fetchone()
    assert row[0] == "tool_call"


def test_record_tool_call_error_writes_tool_error_event():
    sid = ensure_session()
    tid = str(uuid.uuid4())
    with TurnTrace(session_id=sid, source="voice", turn_id=tid):
        record_tool_call(tid, "send_email", {"to": "x"}, "", 5, error="denied")
    flush_writes()
    with connect() as conn:
        row = conn.execute(
            "SELECT type FROM events WHERE turn_id = ?", (tid,)
        ).fetchone()
    assert row[0] == "tool_error"


def test_concurrent_turn_trace_writes_without_busy():
    sid = ensure_session()
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            with TurnTrace(session_id=sid, source="voice") as t:
                t.stt_text = f"utterance number {i}"
                t.llm_ms = 100 + i
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    flush_writes(timeout=3.0)
    assert not errors
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = ?", (sid,)).fetchone()[0]
    assert count == 50
