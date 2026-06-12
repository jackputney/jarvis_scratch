"""Orchestrator skeleton — Phase 1 target; wraps today's pipeline.process_query for now."""

from __future__ import annotations

import threading
from typing import Any, Protocol

from orchestrator.events import EventBus
from orchestrator.types import Command, Job, JobState


class ToolBackend(Protocol):
    """Local registry today; MCP client in Phase 2."""

    def list_definitions(self) -> list[dict[str, Any]]: ...

    def call(self, name: str, inputs: dict[str, Any]) -> str: ...


class Orchestrator:
    """One job at a time. Voice, dashboard, and triggers all submit Commands.

    Phase 1 queue policy (planned): bounded FIFO queue (default max 3). Commands
    wait for the current job instead of receiving 409/busy. Overflow rejects with
    busy — see orchestrator/QUEUE_POLICY.md.
    """

    def __init__(self, bus: EventBus, process_query: callable) -> None:
        self._bus = bus
        self._process_query = process_query
        self._queue: list[Command] = []
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._jobs: dict[str, Job] = {}

    def submit(self, command: Command) -> str:
        with self._lock:
            self._jobs[command.id] = Job(command=command)
            self._queue.append(command)
            self._bus.emit("job.state", job_id=command.id, state=JobState.QUEUED.value)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run_loop, daemon=True)
                self._worker.start()
        return command.id

    def cancel_current(self) -> None:
        self._cancel.set()
        import pipeline

        pipeline.request_interrupt()

    def _run_loop(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                command = self._queue.pop(0)
            self._cancel.clear()
            self._run_one(command)

    def _run_one(self, command: Command) -> None:
        job = self._jobs[command.id]
        job.state = JobState.RUNNING
        self._bus.emit(
            "job.state",
            job_id=command.id,
            state=JobState.RUNNING.value,
            source=command.source.value,
        )
        from config import Config

        result = self._process_query(command.text, Config.load())
        if result.get("busy"):
            job.state = JobState.FAILED
            job.error = "busy"
            job.reply = result.get("reply", "")
        else:
            job.state = JobState.DONE
            job.reply = result.get("reply", "")
        self._bus.emit(
            "job.transcript",
            job_id=command.id,
            heard=command.text,
            reply=job.reply,
            model=result.get("model"),
        )
        self._bus.emit("job.state", job_id=command.id, state=job.state.value)
