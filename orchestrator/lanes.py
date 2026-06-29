"""Lane managers — Phase 1 implementation.

Lane A (VoiceLane): wraps the existing Orchestrator; one active session at a
time. Continues an open idle session on new wake-word if within idle_timeout.

Lane B (BackgroundLane): concurrent background tasks (cron, proactive triggers,
long-running tools). Never blocks the voice lane; queues a spoken notification
to Lane A when the job finishes.

LaneManager: routing decisions — which lane does a given source belong to?

See DOCS/sessions.spec.md for the interface contract this implements.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from orchestrator.events import EventBus
from orchestrator.session import LaneType, SessionState, SessionStore
from orchestrator.types import Command, CommandSource, SubmitResult

logger = logging.getLogger("jarvis.orchestrator.lanes")

_BACKGROUND_SOURCES = {CommandSource.SCHEDULE, CommandSource.WEBHOOK}


class VoiceLane:
    """Wraps the existing Orchestrator for Lane A.

    One active session at a time. New wake-words within ``idle_timeout_sec``
    continue the existing session; outside the window a new session is created.
    """

    idle_timeout_sec: float = 600.0  # 10 min — matches conversation_idle_timeout_sec

    def __init__(
        self,
        orchestrator: Any,
        store: SessionStore,
        bus: EventBus,
    ) -> None:
        self._orchestrator = orchestrator
        self._store = store
        self._bus = bus

    def submit(
        self,
        command: Command,
        session_id: str | None = None,
    ) -> SubmitResult:
        """Submit a command to the voice lane.

        If *session_id* is provided we continue that session; otherwise we
        continue the most-recent idle VOICE session (if within timeout) or
        create a fresh one.
        """
        if session_id:
            session = self._store.get(session_id)
        else:
            session = self._store.get_active(LaneType.VOICE)

        if session is not None and not session.is_expired(self.idle_timeout_sec):
            self._store.mark_active(session.id)
            self._bus.emit(
                "session.continued",
                session_id=session.id,
                turn_count=len(session.turns),
            )
            logger.debug("🔁 Continuing session %s", session.id[:8])
        else:
            if session is not None:
                self._store.close(session.id)
            session = self._store.create(LaneType.VOICE, command.source)
            self._bus.emit(
                "session.created",
                session_id=session.id,
                lane=LaneType.VOICE.value,
                source=command.source.value,
            )
            logger.debug("✨ New voice session %s", session.id[:8])

        result = self._orchestrator.submit(command)
        if result.accepted and result.job_id:
            job = self._orchestrator.get_job(result.job_id)
            if job is not None:
                job.session_id = session.id

        return SubmitResult(
            accepted=result.accepted,
            job_id=result.job_id,
            reason=result.reason,
        )

    def active_session(self):
        """Return the current non-closed VOICE session, or None."""
        return self._store.get_active(LaneType.VOICE)

    def is_busy(self) -> bool:
        return self._orchestrator.queue_depth() > 0


class BackgroundLane:
    """Runs proactive and scheduled tasks without blocking the voice lane.

    Phase 1: manual submit of callables. Phase 2 will add EventBus subscribers
    (calendar, GitHub, cron) that auto-submit here.

    Results are emitted on the EventBus as ``lane.background.complete``.
    When *speak_when_idle* is True, the result is also queued for voice
    playback when Lane A becomes idle (Phase 2 plumbing — noop in Phase 1).
    """

    def __init__(
        self,
        store: SessionStore,
        bus: EventBus,
        max_workers: int = 4,
    ) -> None:
        self._store = store
        self._bus = bus
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="jarvis-bg")
        self._jobs: dict[str, Future[Any]] = {}
        self._lock = threading.Lock()
        self._callbacks: dict[str, list[Callable[[str, Any], None]]] = {}

    def submit(
        self,
        command: Command,
        speak_when_idle: bool = True,
    ) -> SubmitResult:
        """Run *command.text* in the background thread pool.

        Returns a SubmitResult whose job_id is the background job ID.
        A ``lane.background.queued`` event is emitted immediately.
        A ``lane.background.complete`` event is emitted when done.
        """
        session = self._store.create(LaneType.BACKGROUND, command.source)
        job_id = str(uuid.uuid4())

        self._bus.emit(
            "lane.background.queued",
            session_id=session.id,
            job_id=job_id,
            command_preview=command.text[:100],
        )

        def _run() -> Any:
            try:
                return {"text": command.text, "session_id": session.id}
            finally:
                session.close()
                self._bus.emit(
                    "lane.background.complete",
                    session_id=session.id,
                    job_id=job_id,
                )
                with self._lock:
                    for cb in self._callbacks.get(job_id, []):
                        try:
                            cb(job_id, None)
                        except Exception:  # noqa: BLE001
                            logger.warning("⚠️  Background job callback raised", exc_info=True)
                    self._jobs.pop(job_id, None)
                    self._callbacks.pop(job_id, None)

        with self._lock:
            future = self._pool.submit(_run)
            self._jobs[job_id] = future

        return SubmitResult(accepted=True, job_id=job_id)

    def cancel_all(self) -> int:
        """Cancel all pending (not yet started) background jobs. Returns count cancelled."""
        count = 0
        with self._lock:
            for job_id, future in list(self._jobs.items()):
                if future.cancel():
                    count += 1
                    self._jobs.pop(job_id, None)
        logger.debug("🚫 Cancelled %d background jobs", count)
        return count

    def on_complete(self, job_id: str, callback: Callable[[str, Any], None]) -> None:
        """Register a callback invoked when *job_id* finishes."""
        with self._lock:
            self._callbacks.setdefault(job_id, []).append(callback)

    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._jobs)

    def list_active(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"job_id": jid, "done": f.done()}
                for jid, f in self._jobs.items()
            ]

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


class LaneManager:
    """Routing decisions and top-level lane accessors."""

    def __init__(
        self,
        voice: VoiceLane,
        background: BackgroundLane,
    ) -> None:
        self.voice = voice
        self.background = background

    def route(self, source: CommandSource) -> LaneType:
        """Determine which lane a *source* belongs to.

        Background: cron/schedule and webhooks (no user present).
        Voice: everything else (interactive conversation).
        """
        if source in _BACKGROUND_SOURCES:
            return LaneType.BACKGROUND
        return LaneType.VOICE
