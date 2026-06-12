"""Orchestrator core types — Phase 1 spine (not wired to voice loop yet)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class CommandSource(str, Enum):
    VOICE = "voice"
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
    text: str
    source: CommandSource
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)


@dataclass
class Job:
    command: Command
    state: JobState = JobState.QUEUED
    reply: str = ""
    error: str | None = None
