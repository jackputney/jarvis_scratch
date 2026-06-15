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
                """
            )
            conn.commit()
        _initialised = True


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
        conn.commit()


def reset_init_flag_for_tests() -> None:
    """Allow tests to re-run schema init against a patched DB_PATH."""
    global _initialised
    _initialised = False
