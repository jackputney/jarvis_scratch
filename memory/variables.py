"""
memory/variables.py — SQLite-backed key-value store for structured facts about the user.

Examples of stored values: home_city, active_project, wake_time, last_medication.
These are injected into every Claude system prompt as a compact JSON block so Jarvis
always has personal context without burning tokens on long conversation history.
"""

from __future__ import annotations

import json
import sqlite3

from memory.db import DB_PATH, connect, init_db


def _connect() -> sqlite3.Connection:
    init_db()
    return connect()


def set_variable(key: str, value: str) -> None:
    """Persist a key-value fact. Both key and value are stored as text."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO variables (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def get_variable(key: str) -> str | None:
    """Retrieve a stored fact by key. Returns None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM variables WHERE key=?", (key,)
        ).fetchone()
    return row[0] if row else None


def delete_variable(key: str) -> bool:
    """Delete a stored fact. Returns True if a row was removed."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM variables WHERE key=?", (key,))
        conn.commit()
        return cur.rowcount > 0


def get_all_variables() -> dict[str, str]:
    """Return all stored facts as a plain dict."""
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM variables").fetchall()
    return {k: v for k, v in rows}


def build_variables_block() -> str:
    """Return a compact JSON string suitable for injection into a system prompt.

    Returns an empty JSON object string if no variables are stored yet.
    """
    data = get_all_variables()
    if not data:
        return "{}"
    return json.dumps(data, ensure_ascii=False)
