"""Orchestrator core types — Phase 1 spine.

These are the shared value objects passed between command producers (voice loop,
dashboard, future schedulers/webhooks) and the single Orchestrator worker.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class CommandSource(str, Enum):
    VOICE = "voice"
    PHONE = "phone"
    DASHBOARD = "dashboard"
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"
    PLUGIN = "plugin"


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    CANCELLED = "cancelled"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class Command:
    """One unit of work. Immutable so it can be safely shared across threads.

    ``speak`` controls whether the reply is voiced (True for voice turns, False
    for the dashboard text chat which renders the reply on screen instead).
    """

    text: str
    source: CommandSource
    speak: bool = True
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)

    def age_sec(self, now: float | None = None) -> float:
        return (now if now is not None else time.time()) - self.created_at


@dataclass(frozen=True)
class SubmitResult:
    """Returned by Orchestrator.submit — accepted (queued) or rejected (busy)."""

    accepted: bool
    job_id: str | None = None
    reason: str | None = None


@dataclass
class Job:
    command: Command
    state: JobState = JobState.QUEUED
    reply: str = ""
    warning: str | None = None
    error: str | None = None
    model: str | None = None
    capped: bool = False
    latency_ms: int = 0
    cost: float = 0.0
    done_event: threading.Event = field(default_factory=threading.Event)
    session_id: str | None = None

    def wait(self, timeout: float | None = None) -> bool:
        return self.done_event.wait(timeout=timeout)


@dataclass
class Turn:
    """A single request–response pair within a Session."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    command: Command | None = None
    reply: str = ""
    tools_used: list[str] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0
    cost: float = 0.0
    trace_id: str = ""  # links to TurnTrace.turn_id in SQLite
