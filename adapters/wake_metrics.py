"""
adapters/wake_metrics.py -- Wake-word accuracy tracking.

Logs every wake detection event to a SQLite table and exposes
summary / false-positive queries for dashboard or analysis use.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from memory.db import connect


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wake_events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT    NOT NULL,
            detected_word TEXT NOT NULL,
            confidence    REAL NOT NULL,
            accepted      INTEGER NOT NULL,
            source        TEXT NOT NULL
        )
        """
    )


def log_wake_event(
    detected_word: str,
    confidence: float,
    accepted: bool,
    source: str = "mic",
) -> None:
    """Record a single wake-word detection event."""
    with connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO wake_events (timestamp, detected_word, confidence, accepted, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), detected_word, confidence, int(accepted), source),
        )
        conn.commit()


def get_wake_stats(hours: int = 24) -> dict[str, Any]:
    """Aggregate wake detection stats for the last *hours* hours."""
    with connect() as conn:
        _ensure_table(conn)
        cutoff = f"-{hours} hours"
        row = conn.execute(
            """
            SELECT
                COUNT(*)                                                       AS total,
                COALESCE(SUM(accepted), 0)                                     AS accepted,
                COALESCE(SUM(CASE WHEN accepted = 0 THEN 1 ELSE 0 END), 0)    AS rejected,
                AVG(CASE WHEN accepted = 1 THEN confidence END)                AS avg_conf_acc,
                AVG(CASE WHEN accepted = 0 THEN confidence END)                AS avg_conf_rej
            FROM wake_events
            WHERE timestamp >= datetime('now', ?)
            """,
            (cutoff,),
        ).fetchone()
    return {
        "total_detections": row[0],
        "accepted_count": row[1],
        "rejected_count": row[2],
        "avg_confidence_accepted": row[3],
        "avg_confidence_rejected": row[4],
    }


def get_false_positive_candidates(
    hours: int = 24,
    min_confidence: float = 0.3,
) -> list[dict[str, Any]]:
    """Return accepted events whose confidence fell below *min_confidence*."""
    with connect() as conn:
        _ensure_table(conn)
        cutoff = f"-{hours} hours"
        rows = conn.execute(
            "SELECT id, timestamp, detected_word, confidence, source "
            "FROM wake_events "
            "WHERE accepted = 1 AND confidence < ? AND timestamp >= datetime('now', ?) "
            "ORDER BY confidence ASC",
            (min_confidence, cutoff),
        ).fetchall()
    return [
        {"id": r[0], "timestamp": r[1], "detected_word": r[2], "confidence": r[3], "source": r[4]}
        for r in rows
    ]
