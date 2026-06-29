"""Session lifecycle — Phase 1 implementation.

A Session represents one conversation context from first wake-word to idle
timeout or explicit close. The SessionStore is the in-memory registry;
thread-safety is guaranteed by a single lock on all mutating operations.

See DOCS/sessions.spec.md for the interface contract this implements.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from orchestrator.types import CommandSource, Turn

logger = logging.getLogger("jarvis.orchestrator.session")


class LaneType(str, Enum):
    VOICE = "voice"
    BACKGROUND = "background"


class SessionState(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"      # pipeline returned to wake-word; session still open
    CLOSED = "closed"


@dataclass
class Session:
    """One conversation context — open from first wake to idle-timeout or close."""

    id: str
    lane: LaneType
    source: CommandSource
    created_at: float
    last_active_at: float
    state: SessionState
    turns: list[Turn] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ── public methods ───────────────────────────────────────────────────────

    def add_turn(self, turn: Turn) -> None:
        """Append a completed turn and update last_active_at."""
        with self._lock:
            self.turns.append(turn)
            self.last_active_at = time.time()

    def touch(self) -> None:
        """Refresh last_active_at without adding a turn (e.g. mid-response)."""
        with self._lock:
            self.last_active_at = time.time()

    def close(self) -> None:
        with self._lock:
            self.state = SessionState.CLOSED

    def is_expired(self, timeout_sec: float) -> bool:
        return (time.time() - self.last_active_at) >= timeout_sec

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "lane": self.lane.value,
                "source": self.source.value,
                "state": self.state.value,
                "created_at": self.created_at,
                "last_active_at": self.last_active_at,
                "turn_count": len(self.turns),
                "age_sec": round(time.time() - self.created_at, 1),
                "idle_sec": round(time.time() - self.last_active_at, 1),
                "metadata": self.metadata,
            }


class SessionStore:
    """In-memory registry of open sessions. Thread-safe.

    All mutating operations hold ``_lock``. Reads that only need a snapshot
    copy the value out under the lock; callers should not assume stability of
    Session internals without acquiring Session._lock themselves.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    # ── factory ──────────────────────────────────────────────────────────────

    def create(
        self,
        lane: LaneType,
        source: CommandSource,
        **metadata: Any,
    ) -> Session:
        """Create, register, and return a new ACTIVE session."""
        now = time.time()
        session = Session(
            id=str(uuid.uuid4()),
            lane=lane,
            source=source,
            created_at=now,
            last_active_at=now,
            state=SessionState.ACTIVE,
            metadata=dict(metadata),
        )
        with self._lock:
            self._sessions[session.id] = session
        logger.debug("🗂️  Session created: %s (lane=%s source=%s)", session.id[:8], lane.value, source.value)
        return session

    # ── lookups ──────────────────────────────────────────────────────────────

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def get_active(self, lane: LaneType) -> Session | None:
        """Return the most-recently-active non-closed session for *lane*, or None."""
        with self._lock:
            candidates = [
                s for s in self._sessions.values()
                if s.lane == lane and s.state != SessionState.CLOSED
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.last_active_at)

    def all_active(self) -> list[Session]:
        """Return all sessions that are not CLOSED."""
        with self._lock:
            return [s for s in self._sessions.values() if s.state != SessionState.CLOSED]

    # ── lifecycle ────────────────────────────────────────────────────────────

    def close(self, session_id: str) -> None:
        session = self.get(session_id)
        if session is None:
            return
        session.close()
        logger.debug("🗂️  Session closed: %s", session_id[:8])

    def close_idle(self, older_than_sec: float) -> int:
        """Close all non-CLOSED sessions idle longer than *older_than_sec*. Returns count."""
        closed = 0
        with self._lock:
            targets = list(self._sessions.values())
        for session in targets:
            if session.state != SessionState.CLOSED and session.is_expired(older_than_sec):
                session.close()
                closed += 1
                logger.debug(
                    "🗂️  Session idle-expired: %s (idle %.0fs)",
                    session.id[:8],
                    time.time() - session.last_active_at,
                )
        return closed

    def mark_idle(self, session_id: str) -> None:
        """Transition an ACTIVE session to IDLE (pipeline returned to wake-word listen)."""
        session = self.get(session_id)
        if session is None:
            return
        with session._lock:
            if session.state == SessionState.ACTIVE:
                session.state = SessionState.IDLE

    def mark_active(self, session_id: str) -> None:
        """Transition an IDLE session back to ACTIVE (new turn started)."""
        session = self.get(session_id)
        if session is None:
            return
        with session._lock:
            if session.state == SessionState.IDLE:
                session.state = SessionState.ACTIVE
