"""
events.py — Thread-safe in-memory event bus + conversation persistence.

A single source of truth that both the orb UI and the Flask dashboard read from,
without any external event-bus library:

  • a bounded in-memory deque of recent events (state changes, errors, etc.)
  • a small shared state dict (pipeline state, mute, uptime)
  • a `conversations` SQLite table (last exchanges with model/latency/cost)

All access is guarded by a lock so the pipeline thread, the Qt thread, and the
dashboard's request threads can read/write concurrently.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

from memory.db import DB_PATH, connect, init_db

logger = logging.getLogger("jarvis.events")
MAX_EVENTS = 200

_lock = threading.Lock()
_events: deque[dict] = deque(maxlen=MAX_EVENTS)
_state: dict[str, Any] = {
    "pipeline_state": "IDLE",  # IDLE | LISTENING | THINKING | SPEAKING | FOLLOWUP_WINDOW | WAITING_CONFIRM
    "muted": False,
    "started_at": time.time(),
}

_init_lock = threading.Lock()
_initialised = True  # schema owned by memory.db.init_db()

_state_listeners: list[Callable[[str], None]] = []
_dev_mode = os.environ.get("JARVIS_DEV", "").strip().lower() in ("1", "true", "yes")


def _connect() -> sqlite3.Connection:
    init_db()
    return connect()


# ---------------------------------------------------------------------------
# In-memory events + state
# ---------------------------------------------------------------------------

def emit(event_type: str, **data: Any) -> None:
    """Append an event to the in-memory ring buffer."""
    with _lock:
        _events.append({"ts": datetime.now().isoformat(), "type": event_type, **data})


def subscribe_pipeline_state(callback: Callable[[str], None]) -> None:
    """Register a listener for pipeline state changes (single source of truth)."""
    with _lock:
        if callback not in _state_listeners:
            _state_listeners.append(callback)


def unsubscribe_pipeline_state(callback: Callable[[str], None]) -> None:
    with _lock:
        try:
            _state_listeners.remove(callback)
        except ValueError:
            pass


def get_pipeline_state() -> str:
    with _lock:
        return str(_state.get("pipeline_state", "IDLE"))


def set_pipeline_state(state: str) -> None:
    with _lock:
        prev = _state["pipeline_state"]
        _state["pipeline_state"] = state
        listeners = list(_state_listeners)
    if prev != state:
        logger.info("STATE: %s → %s", prev, state)
    emit("state", state=state)
    for cb in listeners:
        try:
            cb(state)
        except Exception:  # noqa: BLE001
            logger.debug("pipeline state listener failed for %s", state, exc_info=True)


def set_muted(muted: bool) -> None:
    with _lock:
        _state["muted"] = bool(muted)


def get_state() -> dict:
    """Return a snapshot of the shared state plus uptime in seconds."""
    with _lock:
        snapshot = dict(_state)
    snapshot["uptime_seconds"] = int(time.time() - snapshot["started_at"])
    return snapshot


def get_recent_events(limit: int = 50) -> list[dict]:
    with _lock:
        return list(_events)[-limit:]


# ---------------------------------------------------------------------------
# Conversation persistence
# ---------------------------------------------------------------------------

def record_conversation(
    heard: str,
    response: str,
    model: str,
    latency_ms: int,
    cost_usd: float,
) -> None:
    """Persist one exchange and emit a corresponding event."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO conversations "
            "(timestamp, heard, response, model, latency_ms, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), heard, response, model, int(latency_ms), float(cost_usd)),
        )
        conn.commit()
    emit("conversation", heard=heard, response=response, model=model,
         latency_ms=latency_ms, cost_usd=cost_usd)


def get_recent_conversations(limit: int = 50) -> list[dict]:
    """Return the most recent exchanges, newest last."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT timestamp, heard, response, model, latency_ms, cost_usd "
            "FROM conversations ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    cols = ["timestamp", "heard", "response", "model", "latency_ms", "cost_usd"]
    return [dict(zip(cols, row)) for row in reversed(rows)]
