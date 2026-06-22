"""Orchestrator — the Phase 1 spine.

One worker thread owns execution. Voice, dashboard, and (future) triggers all
``submit()`` Commands instead of calling the pipeline directly. This gives us:

  • a single serialisation point (no two queries running at once),
  • a bounded FIFO queue so a follow-up enqueues instead of being rejected,
  • stale-command dropping (a wake-word from 60 s ago shouldn't fire now),
  • an event bus other surfaces subscribe to (dashboard SSE, loggers, the orb).

The Orchestrator owns the *reply side* of a turn: it runs the query, drives the
pipeline state (THINKING → WAITING_CONFIRM → SPEAKING → IDLE) and, for voice
commands, speaks the reply. Producers just submit and optionally wait.

See orchestrator/QUEUE_POLICY.md for the queue-depth decision.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from orchestrator.events import EventBus
from orchestrator.types import Command, CommandSource, Job, JobState, SubmitResult

logger = logging.getLogger("jarvis.orchestrator")

DEFAULT_MAX_QUEUE_DEPTH = 3
DEFAULT_MAX_COMMAND_AGE_SEC = 60.0

ProcessQuery = Callable[..., dict[str, Any]]
Speak = Callable[..., None]


class Orchestrator:
    def __init__(
        self,
        bus: EventBus,
        process_query: ProcessQuery,
        speak: Speak | None = None,
        config_loader: Callable[[], Any] | None = None,
        max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
        max_command_age_sec: float = DEFAULT_MAX_COMMAND_AGE_SEC,
        interrupt_event: threading.Event | None = None,
        request_interrupt: Callable[[], None] | None = None,
        clear_interrupt: Callable[[], None] | None = None,
    ) -> None:
        self._bus = bus
        self._process_query = process_query
        self._speak = speak
        self._config_loader = config_loader
        self._max_queue = max_queue_depth
        self._max_age = max_command_age_sec

        self._interrupt_event = interrupt_event
        self._request_interrupt = request_interrupt
        self._clear_interrupt = clear_interrupt

        self._cv = threading.Condition()
        self._queue: deque[Command] = deque()
        self._jobs: dict[str, Job] = {}
        self._current_job_id: str | None = None
        self._ui_cb: Callable[[str], None] | None = None
        self._stop = threading.Event()

        self._worker = threading.Thread(
            target=self._run_loop, name="jarvis-orchestrator", daemon=True
        )
        self._worker.start()

    # -- public API ---------------------------------------------------------

    def set_state_callback(self, cb: Callable[[str], None] | None) -> None:
        """Register the UI bridge (e.g. orb FaceWidget.set_state). Optional."""
        self._ui_cb = cb

    def submit(self, command: Command) -> SubmitResult:
        emit: list[tuple[str, dict[str, Any]]] = []
        with self._cv:
            self._purge_stale_locked(emit)
            busy = self._current_job_id is not None
            if busy and len(self._queue) >= self._max_queue:
                logger.warning(
                    "⏳ Queue full (%d waiting) — rejecting %s command.",
                    len(self._queue), command.source.value,
                )
                self._flush(emit)
                return SubmitResult(accepted=False, reason="busy")
            self._jobs[command.id] = Job(command=command)
            self._queue.append(command)
            emit.append(("job.state", {
                "job_id": command.id,
                "state": JobState.QUEUED.value,
                "source": command.source.value,
            }))
            self._cv.notify()
        self._flush(emit)
        return SubmitResult(accepted=True, job_id=command.id)

    def wait(self, job_id: str, timeout: float | None = None) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.wait(timeout=timeout)
        return job

    def cancel_current(self) -> None:
        """Stop the running turn and drop everything still queued."""
        from improvement.trace import cancel_active_trace
        from tts.router import stop_speech

        self._do_request_interrupt()
        cancel_active_trace(interrupted=True)
        stop_speech()
        self._set_state("IDLE")
        emit: list[tuple[str, dict[str, Any]]] = []
        with self._cv:
            while self._queue:
                cmd = self._queue.popleft()
                self._mark_cancelled_locked(cmd, "cancelled", emit)
        self._flush(emit)

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def queue_depth(self) -> int:
        with self._cv:
            return len(self._queue)

    def shutdown(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()

    # -- worker -------------------------------------------------------------

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            command: Command | None = None
            emit: list[tuple[str, dict[str, Any]]] = []
            with self._cv:
                self._purge_stale_locked(emit)
                while not self._queue and not self._stop.is_set():
                    self._cv.wait(timeout=1.0)
                    self._purge_stale_locked(emit)
                if self._stop.is_set():
                    self._flush(emit)
                    return
                command = self._queue.popleft()
                self._current_job_id = command.id
            self._flush(emit)
            if command is not None:
                try:
                    self._run_one(command)
                finally:
                    with self._cv:
                        self._current_job_id = None

    def _run_one(self, command: Command) -> Job:
        job = self._jobs[command.id]
        self._do_clear_interrupt()
        job.state = JobState.RUNNING
        self._emit("job.state", job_id=command.id, state=JobState.RUNNING.value,
                   source=command.source.value)
        self._set_state("THINKING")
        cfg = self._config_loader() if self._config_loader else None

        from improvement.trace import TurnTrace, ensure_session, pop_stt_metrics

        session_id = ensure_session(model=getattr(cfg, "claude_model_fast", "") if cfg else "")
        stt_meta = pop_stt_metrics(command.text)
        trace_source = _trace_source(command.source)

        sentence_q: queue.Queue[str | None] | None = None
        tts_thread: threading.Thread | None = None
        tts_audio_started = False
        result: dict[str, Any] = {}
        use_stream_tts = (
            command.speak
            and cfg is not None
            and getattr(cfg, "streaming_tts", True)
        )
        try:
            with TurnTrace(session_id=session_id, source=trace_source) as trace:
                trace.stt_text = command.text
                trace.stt_confidence = stt_meta.get("stt_confidence")
                trace.stt_ms = stt_meta.get("stt_ms")
                trace.wake_latency_ms = stt_meta.get("wake_latency_ms")
                if use_stream_tts:
                    sentence_q = queue.Queue()

                    def _sentence_iter():
                        while True:
                            item = sentence_q.get()
                            if item is None:
                                return
                            yield item

                    def _mark_speaking() -> None:
                        nonlocal tts_audio_started
                        tts_audio_started = True
                        self._set_state("SPEAKING")

                    def _run_stream_tts() -> None:
                        from tts.router import speak_stream

                        speak_stream(
                            _sentence_iter(),
                            voice_id=None,
                            on_first_chunk=_mark_speaking,
                        )

                    tts_thread = threading.Thread(
                        target=_run_stream_tts,
                        daemon=True,
                        name="jarvis-tts-stream",
                    )
                    tts_thread.start()
                    result = self._process_query(
                        command.text,
                        cfg,
                        on_state=self._set_state,
                        speak=False,
                        on_sentence=sentence_q.put,
                    )
                else:
                    result = self._process_query(
                        command.text, cfg, on_state=self._set_state, speak=command.speak,
                    )
                job.reply = result.get("reply", "")
                job.warning = result.get("warning")
                job.model = result.get("model")
                job.capped = bool(result.get("capped", False))
                job.latency_ms = int(result.get("latency_ms", 0) or 0)
                job.cost = float(result.get("cost", 0.0) or 0.0)
                trace.model = job.model or ""
                trace.llm_ms = job.latency_ms
                trace.tokens_in = result.get("tokens_in")
                trace.tokens_out = result.get("tokens_out")
                trace.cache_read_tokens = result.get("cache_read_tokens")
                if result.get("tts_provider"):
                    trace.details["tts_provider"] = result["tts_provider"]
                if result.get("tts_ms") is not None:
                    trace.tts_ms = int(result["tts_ms"])
                if result.get("busy"):
                    job.state, job.error = JobState.FAILED, "busy"
                elif self._interrupt_set():
                    job.state = JobState.CANCELLED
                    trace.cancelled = True
                    import events

                    if events.get_state().get("pipeline_state") == "SPEAKING":
                        trace.interrupted = True
                else:
                    job.state = JobState.DONE

                if job.reply.strip():
                    self._emit("job.transcript", job_id=command.id, heard=command.text,
                               reply=job.reply, model=job.model, state=job.state.value)
                elif command.source == CommandSource.SCHEDULE:
                    logger.debug("Empty reply from scheduled plugin — no TTS.")

                speakable = (
                    command.speak
                    and bool(job.reply.strip())
                    and job.state in (JobState.DONE, JobState.FAILED)
                    and not self._interrupt_set()
                    and not bool(result.get("stream_spoken"))
                )
                if speakable:
                    spoken = f"{job.warning} {job.reply}" if job.warning else job.reply
                    self._set_state("SPEAKING")
                    t0 = time.monotonic()
                    self._do_speak(spoken, cfg)
                    if trace.tts_ms is None:
                        trace.tts_ms = int((time.monotonic() - t0) * 1000)
                    if self._interrupt_set():
                        trace.interrupted = True
        except Exception as exc:  # noqa: BLE001
            logger.error("⚠️  Job %s failed: %s", command.id, exc, exc_info=True)
            job.state = JobState.FAILED
            job.error = str(exc)
            if not job.reply:
                job.reply = "Sorry, something went wrong handling that."
        finally:
            if sentence_q is not None:
                sentence_q.put(None)
            if tts_thread is not None:
                while tts_thread.is_alive():
                    if self._interrupt_set():
                        from tts.router import stop_speech

                        stop_speech()
                        break
                    tts_thread.join(timeout=0.1)
                tts_thread.join()
            # stream_spoken without playback leaves the user silent — speak the full reply.
            if (
                use_stream_tts
                and command.speak
                and not self._interrupt_set()
                and job.state in (JobState.DONE, JobState.FAILED)
                and bool(job.reply.strip())
                and bool(result.get("stream_spoken"))
                and not tts_audio_started
            ):
                spoken = f"{job.warning} {job.reply}" if job.warning else job.reply
                self._set_state("SPEAKING")
                self._do_speak(spoken, cfg)
            self._set_state("IDLE")
            self._emit("job.state", job_id=command.id, state=job.state.value)
            job.done_event.set()
            if job.state in (JobState.DONE, JobState.FAILED, JobState.CANCELLED):
                threading.Timer(300, lambda jid=command.id: self._jobs.pop(jid, None)).start()
        return job

    # -- helpers ------------------------------------------------------------

    def _purge_stale_locked(self, emit: list[tuple[str, dict[str, Any]]]) -> None:
        if not self._queue:
            return
        now = time.time()
        kept: deque[Command] = deque()
        for cmd in self._queue:
            if cmd.age_sec(now) > self._max_age:
                logger.info("🗑️  Dropping stale %s command (age %.0fs).",
                            cmd.source.value, cmd.age_sec(now))
                self._mark_cancelled_locked(cmd, "stale", emit)
            else:
                kept.append(cmd)
        self._queue = kept

    def _mark_cancelled_locked(
        self, cmd: Command, reason: str, emit: list[tuple[str, dict[str, Any]]]
    ) -> None:
        job = self._jobs.get(cmd.id)
        if job is not None:
            job.state = JobState.CANCELLED
            job.error = reason
            job.done_event.set()
        emit.append(("job.state", {
            "job_id": cmd.id,
            "state": JobState.CANCELLED.value,
            "reason": reason,
        }))

    def _set_state(self, name: str) -> None:
        self._emit("pipeline.state", state=name)
        # events.set_pipeline_state via bus subscriber (_sync_legacy in runtime).

    def _do_speak(self, text: str, cfg: Any) -> None:
        if self._speak is None:
            return
        try:
            self._speak(text)
        except Exception:  # noqa: BLE001
            logger.error("⚠️  TTS failed.", exc_info=True)

    def _emit(self, event: str, **payload: Any) -> None:
        self._bus.emit(event, **payload)

    def _flush(self, emit: list[tuple[str, dict[str, Any]]]) -> None:
        for event, payload in emit:
            self._bus.emit(event, **payload)
        emit.clear()

    def _interrupt_set(self) -> bool:
        if self._interrupt_event is not None:
            return self._interrupt_event.is_set()
        import pipeline

        return pipeline._interrupt.is_set()

    def _do_request_interrupt(self) -> None:
        if self._request_interrupt is not None:
            self._request_interrupt()
            return
        import pipeline

        pipeline.request_interrupt()

    def _do_clear_interrupt(self) -> None:
        if self._clear_interrupt is not None:
            self._clear_interrupt()
            return
        import pipeline

        pipeline._clear_interrupt()


def _trace_source(source: CommandSource) -> str:
    if source == CommandSource.VOICE:
        return "voice"
    if source == CommandSource.DASHBOARD:
        return "dashboard"
    if source in (CommandSource.SCHEDULE, CommandSource.PLUGIN, CommandSource.WEBHOOK):
        return "plugin"
    return source.value
