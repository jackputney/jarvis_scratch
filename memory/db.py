"""
memory/db.py — Single SQLite initialisation for Jarvis persistence.

All tables live in memory/variables.db. Call init_db() once at startup so
dashboard CRUD and the pipeline never hit a missing-table race on first run.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent / "variables.db"

_init_lock = threading.Lock()
_initialised = False


def connect(timeout: float = 5.0) -> sqlite3.Connection:
    """Open the shared Jarvis DB (WAL mode, busy timeout)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
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
                """
            )
            conn.commit()
        _initialised = True


def reset_init_flag_for_tests() -> None:
    """Allow tests to re-run schema init against a patched DB_PATH."""
    global _initialised
    _initialised = False
