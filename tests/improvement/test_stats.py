"""Improvement stats API tests."""

from __future__ import annotations

import json
import uuid

import pytest

from dashboard.app import create_app
from improvement.trace import TurnTrace, ensure_session, flush_writes, reset_writer_for_tests
from memory.db import connect, init_db


@pytest.fixture
def client(temp_env):
    reset_writer_for_tests()
    init_db()
    app = create_app()
    app.config.update(TESTING=True)
    yield app.test_client()
    flush_writes()
    reset_writer_for_tests()


def _seed_turns(session_id: str) -> None:
    with TurnTrace(session_id=session_id, source="voice") as t:
        t.stt_text = "send email to Jeff"
        t.llm_ms = 500
    flush_writes()
    tid = str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO turns (turn_id, session_id, ts, source, total_ms, stt_text)
            VALUES (?, ?, datetime('now'), 'voice', ?, ?)
            """,
            (tid, session_id, 2000, "send email to Jeff again"),
        )
        conn.execute(
            """
            INSERT INTO corrections (correction_id, turn_id, prev_turn_id, kind)
            VALUES (?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), tid, str(uuid.uuid4()), "asr_correction"),
        )
        conn.execute(
            """
            INSERT INTO events (event_id, turn_id, ts, type, payload_json)
            VALUES (?, ?, datetime('now'), 'tool_call', ?)
            """,
            (str(uuid.uuid4()), tid, json.dumps({"tool_name": "send_email"})),
        )
        conn.execute(
            """
            INSERT INTO events (event_id, turn_id, ts, type, payload_json)
            VALUES (?, ?, datetime('now'), 'tool_error', ?)
            """,
            (str(uuid.uuid4()), tid, json.dumps({"tool_name": "send_email"})),
        )
        conn.execute(
            """
            INSERT INTO events (event_id, turn_id, ts, type, payload_json)
            VALUES (?, ?, datetime('now'), 'tts_fallback', '{}')
            """,
            (str(uuid.uuid4()), tid),
        )
        conn.commit()


def test_improvement_stats_shape(client):
    sid = ensure_session()
    _seed_turns(sid)
    data = client.get("/api/improvement/stats").get_json()
    assert {
        "total_turns",
        "avg_total_ms",
        "p95_total_ms",
        "correction_rate",
        "tool_error_rate",
        "tts_fallback_rate",
        "top_tools",
    } <= data.keys()
    assert data["total_turns"] >= 2
    assert data["correction_rate"] > 0
    assert data["tool_error_rate"] > 0
    assert data["tts_fallback_rate"] > 0
    assert isinstance(data["top_tools"], list)


def test_improvement_turns_endpoint(client):
    sid = ensure_session()
    _seed_turns(sid)
    data = client.get("/api/improvement/turns?limit=10").get_json()
    assert "turns" in data
    assert len(data["turns"]) >= 1
    assert "total_ms" in data["turns"][0]
