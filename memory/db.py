"""
memory/db.py — Single SQLite initialisation for Jarvis persistence.

All tables live in memory/variables.db. Call init_db() once at startup so
dashboard CRUD and the pipeline never hit a missing-table race on first run.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from memory import store

_init_lock = threading.Lock()
_initialised = False

# Legacy alias — tests may patch this; connect() uses store.variables_db_path().
DB_PATH = Path(__file__).parent / "variables.db"


def connect(timeout: float = 5.0) -> sqlite3.Connection:
    """Open the shared Jarvis DB (WAL mode, busy timeout)."""
    path = store.variables_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Create all tables if missing. Safe to call multiple times."""
    global _initialised
    if _initialised:
        return
    with _init_lock:
        if _initialised:
            return
        with connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS variables (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    query_preview TEXT
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    heard TEXT,
                    response TEXT,
                    model TEXT,
                    latency_ms INTEGER,
                    cost_usd REAL
                );
                CREATE TABLE IF NOT EXISTS tool_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    inputs TEXT,
                    result TEXT,
                    ok INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    platform TEXT,
                    app_version TEXT,
                    model TEXT
                );
                CREATE TABLE IF NOT EXISTS turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    ts TEXT NOT NULL,
                    source TEXT,
                    wake_latency_ms INTEGER,
                    stt_text TEXT,
                    stt_confidence REAL,
                    stt_ms INTEGER,
                    llm_ms INTEGER,
                    tool_ms INTEGER,
                    tts_ms INTEGER,
                    total_ms INTEGER,
                    model TEXT,
                    tokens_in INTEGER,
                    tokens_out INTEGER,
                    cache_read_tokens INTEGER,
                    interrupted INTEGER DEFAULT 0,
                    cancelled INTEGER DEFAULT 0,
                    details_json TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    turn_id TEXT,
                    ts TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload_json TEXT
                );
                CREATE TABLE IF NOT EXISTS corrections (
                    correction_id TEXT PRIMARY KEY,
                    turn_id TEXT,
                    prev_turn_id TEXT,
                    kind TEXT
                );
                CREATE TABLE IF NOT EXISTS lessons (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    category TEXT,
                    text TEXT,
                    status TEXT DEFAULT 'pending',
                    evidence_turn_ids TEXT,
                    votes INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS suggestions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    title TEXT,
                    body TEXT,
                    category TEXT,
                    severity TEXT,
                    status TEXT DEFAULT 'pending',
                    evidence_json TEXT,
                    proposed_change TEXT,
                    github_issue_url TEXT
                );
                CREATE TABLE IF NOT EXISTS baselines (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    metric TEXT,
                    p50 REAL,
                    p95 REAL,
                    p99 REAL,
                    value REAL
                );
                CREATE INDEX IF NOT EXISTS idx_turns_session_ts ON turns(session_id, ts);
                CREATE INDEX IF NOT EXISTS idx_events_turn_id ON events(turn_id);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
                """
            )
            conn.commit()
            try:
                conn.execute("ALTER TABLE suggestions ADD COLUMN github_issue_url TEXT")
                conn.commit()
            except Exception:  # noqa: BLE001
                pass

            _scrub_corrupt_telemetry(conn)

        _initialised = True


def _scrub_corrupt_telemetry(conn: sqlite3.Connection) -> None:
    """Remove known-corrupt rows created by instrumentation bugs.

    Two classes of corrupt data are cleaned up here on startup:

    1. Self-referential corrections (turn_id == prev_turn_id): caused by a
       duplicate _apply_signal_detections() call in TurnTrace.__exit__ that
       compared each turn against itself, generating a spurious asr_correction
       for every single turn.  Fixed in improvement/trace.py (sprint-9).

    2. Synthetic 'trace'/'slow' turns: injected by scripted benchmark runs
       into the production DB, polluting correction_rate and latency metrics.
       Their origin is unclear; they always appear in voice/dashboard pairs
       at identical timestamps and are never real user utterances.
    """
    import logging as _logging

    _log = _logging.getLogger("jarvis.db.scrub")

    deleted_corrections = conn.execute(
        "DELETE FROM corrections WHERE turn_id = prev_turn_id"
    ).rowcount
    conn.commit()
    if deleted_corrections:
        _log.info(
            "🧹 Scrubbed %d self-referential correction rows (instrumentation bug fixed).",
            deleted_corrections,
        )

    deleted_turns = conn.execute(
        "DELETE FROM turns WHERE stt_text IN ('trace', 'slow')"
    ).rowcount
    conn.commit()
    if deleted_turns:
        _log.info(
            "🧹 Scrubbed %d synthetic benchmark turns ('trace'/'slow') from production DB.",
            deleted_turns,
        )


def enforce_retention(retention_days: int = 90) -> None:
    """Delete old usage and conversation rows."""
    days = max(1, int(retention_days))
    with connect() as conn:
        conn.execute(
            "DELETE FROM usage_log WHERE timestamp < datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.execute(
            "DELETE FROM conversations WHERE timestamp < datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.execute(
            "DELETE FROM tool_runs WHERE timestamp < datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.execute(
            "DELETE FROM events WHERE ts < datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.execute(
            "DELETE FROM turns WHERE ts < datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.execute(
            "DELETE FROM corrections WHERE correction_id IN ("
            "SELECT correction_id FROM corrections c "
            "LEFT JOIN turns t ON c.turn_id = t.turn_id WHERE t.turn_id IS NULL"
            ")",
        )
        conn.commit()


def reset_init_flag_for_tests() -> None:
    """Allow tests to re-run schema init against a patched DB_PATH."""
    global _initialised
    _initialised = False
