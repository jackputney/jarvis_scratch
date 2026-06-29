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
    set_eval_mode,
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


def _correction_rows(turn_id: str | None = None) -> list[dict]:
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        if turn_id:
            rows = conn.execute(
                "SELECT * FROM corrections WHERE turn_id = ?", (turn_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM corrections").fetchall()
    return [dict(r) for r in rows]


def test_single_turn_generates_no_corrections():
    """One turn in a session should not produce any correction record."""
    sid = ensure_session()
    tid = str(uuid.uuid4())
    with TurnTrace(session_id=sid, source="voice", turn_id=tid) as t:
        t.stt_text = "what time is it"
    flush_writes()
    assert _correction_rows(tid) == [], "single turn must not self-correct"


def test_second_turn_same_text_generates_exactly_one_correction():
    """Repeating the same text in consecutive turns is one asr_correction — not two."""
    sid = str(uuid.uuid4())
    tid1 = str(uuid.uuid4())
    tid2 = str(uuid.uuid4())
    with TurnTrace(session_id=sid, source="voice", turn_id=tid1) as t:
        t.stt_text = "trace"
    flush_writes()
    with TurnTrace(session_id=sid, source="voice", turn_id=tid2) as t:
        t.stt_text = "trace"
    flush_writes()
    rows = _correction_rows(tid2)
    assert len(rows) == 1, f"expected 1 correction, got {len(rows)}: {rows}"
    assert rows[0]["prev_turn_id"] == tid1, "prev_turn_id must point to the previous turn"
    assert rows[0]["turn_id"] != rows[0]["prev_turn_id"], "turn must not self-reference"


def test_no_self_referential_corrections_across_session():
    """No correction record should ever have turn_id == prev_turn_id."""
    sid = str(uuid.uuid4())
    texts = ["open spotify", "open spotify", "what time is it", "open spotify"]
    for text in texts:
        with TurnTrace(session_id=sid, source="voice") as t:
            t.stt_text = text
    flush_writes()
    self_refs = [
        r for r in _correction_rows()
        if r["turn_id"] == r["prev_turn_id"]
    ]
    assert self_refs == [], f"self-referential corrections found: {self_refs}"


def test_eval_mode_suppresses_turn_writes():
    """Turns recorded inside eval mode must not appear in the production DB."""
    sid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    set_eval_mode(True)
    try:
        with TurnTrace(session_id=sid, source="voice", turn_id=tid) as t:
            t.stt_text = "trace"
        flush_writes()
    finally:
        set_eval_mode(False)
    assert _turn_row(tid) is None, "eval-mode turn must not be written to DB"
    assert _correction_rows(tid) == [], "eval-mode must not write corrections"


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
