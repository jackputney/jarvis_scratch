"""Turn-level instrumentation — async SQLite writer, TurnTrace context manager."""

from __future__ import annotations

import json
import logging
import platform
import queue
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from improvement.signals import detect_correction, detect_repeat_request
from memory.db import connect

logger = logging.getLogger("jarvis.improvement.trace")

APP_VERSION = "dev"
_write_queue: queue.Queue[tuple[str, tuple[Any, ...]] | None] = queue.Queue()
_writer_thread: threading.Thread | None = None
_writer_lock = threading.Lock()

_session_id: str | None = None
_session_lock = threading.Lock()

_session_last_turn: dict[str, tuple[str, str]] = {}
_session_history: dict[str, list[str]] = {}

_stt_stash_lock = threading.Lock()
_stt_stash: dict[str, dict[str, Any]] = {}

_active_trace: ContextVar["TurnTrace | None"] = ContextVar("active_turn_trace", default=None)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_writer() -> None:
    global _writer_thread
    with _writer_lock:
        if _writer_thread is not None and _writer_thread.is_alive():
            return

        def _loop() -> None:
            conn = connect()
            while True:
                item = _write_queue.get()
                if item is None:
                    break
                op, args = item
                try:
                    if op == "session":
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO sessions
                            (session_id, started_at, platform, app_version, model)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            args,
                        )
                    elif op == "turn":
                        conn.execute(
                            """
                            INSERT INTO turns (
                                turn_id, session_id, ts, source, wake_latency_ms,
                                stt_text, stt_confidence, stt_ms, llm_ms, tool_ms,
                                tts_ms, total_ms, model, tokens_in, tokens_out,
                                cache_read_tokens, interrupted, cancelled, details_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            args,
                        )
                    elif op == "event":
                        conn.execute(
                            """
                            INSERT INTO events (event_id, turn_id, ts, type, payload_json)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            args,
                        )
                    elif op == "correction":
                        conn.execute(
                            """
                            INSERT INTO corrections
                            (correction_id, turn_id, prev_turn_id, kind)
                            VALUES (?, ?, ?, ?)
                            """,
                            args,
                        )
                    conn.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.error("⚠️  Improvement write failed (%s): %s", op, exc, exc_info=True)

        _writer_thread = threading.Thread(target=_loop, name="jarvis-improve-writer", daemon=True)
        _writer_thread.start()


def _enqueue(op: str, *args: Any) -> None:
    _ensure_writer()
    _write_queue.put((op, args))


def shutdown_writer() -> None:
    """Flush and stop the background writer (tests)."""
    global _writer_thread
    if _writer_thread is None:
        return
    _write_queue.put(None)
    _writer_thread.join(timeout=5.0)
    _writer_thread = None


def flush_writes(timeout: float = 2.0) -> None:
    """Wait until queued improvement writes are likely flushed (tests)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _write_queue.empty():
            time.sleep(0.05)
            if _write_queue.empty():
                return
        time.sleep(0.02)


def reset_writer_for_tests() -> None:
    """Restart writer thread against a fresh test DB."""
    global _writer_thread, _write_queue, _session_id
    shutdown_writer()
    _write_queue = queue.Queue()
    _writer_thread = None
    _session_id = None
    with _stt_stash_lock:
        _stt_stash.clear()
    _session_last_turn.clear()
    _session_history.clear()


def get_active_trace() -> TurnTrace | None:
    return _active_trace.get()


def stash_stt_metrics(
    text: str,
    *,
    confidence: float | None,
    stt_ms: int,
    wake_latency_ms: int | None = None,
) -> None:
    """Pipeline stores STT metrics before orchestrator opens TurnTrace."""
    key = (text or "").strip()
    if not key:
        return
    with _stt_stash_lock:
        _stt_stash[key] = {
            "stt_confidence": confidence,
            "stt_ms": stt_ms,
            "wake_latency_ms": wake_latency_ms,
        }


def pop_stt_metrics(text: str) -> dict[str, Any]:
    key = (text or "").strip()
    with _stt_stash_lock:
        return _stt_stash.pop(key, {})


def ensure_session(*, model: str = "") -> str:
    global _session_id
    with _session_lock:
        if _session_id is not None:
            return _session_id
        sid = str(uuid.uuid4())
        _enqueue(
            "session",
            sid,
            _utc_now_iso(),
            platform.system().lower(),
            APP_VERSION,
            model or "",
        )
        _session_id = sid
        return sid


def _last_turn_text(session_id: str) -> tuple[str | None, str | None]:
    return _session_last_turn.get(session_id, (None, None))


def _recent_turn_texts(session_id: str, limit: int = 3) -> list[str]:
    hist = _session_history.get(session_id, [])
    return hist[-limit:]


def record_event(turn_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
    _enqueue(
        "event",
        str(uuid.uuid4()),
        turn_id,
        _utc_now_iso(),
        event_type,
        json.dumps(payload or {}, default=str),
    )


def record_tool_call(
    turn_id: str,
    tool_name: str,
    args: dict[str, Any] | None,
    result: str,
    latency_ms: int,
    *,
    error: str | None = None,
) -> None:
    payload = {
        "tool_name": tool_name,
        "args": args or {},
        "result_preview": (result or "")[:500],
        "latency_ms": latency_ms,
    }
    if error:
        payload["error"] = error[:500]
        record_event(turn_id, "tool_error", payload)
    else:
        record_event(turn_id, "tool_call", payload)


@dataclass
class TurnTrace:
    """Context manager recording one orchestrator turn."""

    session_id: str
    source: str
    turn_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    stt_text: str = ""
    stt_confidence: float | None = None
    stt_ms: int | None = None
    wake_latency_ms: int | None = None
    llm_ms: int | None = None
    tool_ms: int = 0
    tts_ms: int | None = None
    model: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    cache_read_tokens: int | None = None
    interrupted: bool = False
    cancelled: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    _started: float = field(default_factory=time.monotonic, repr=False)
    _events: list[tuple[str, dict[str, Any]]] = field(default_factory=list, repr=False)
    _token: Any = field(default=None, repr=False)

    def __enter__(self) -> TurnTrace:
        self._token = _active_trace.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _active_trace.reset(self._token)
            self._token = None

        total_ms = int((time.monotonic() - self._started) * 1000)
        details_json = json.dumps(self.details, default=str) if self.details else None

        self._apply_signal_detections()

        _enqueue(
            "turn",
            self.turn_id,
            self.session_id,
            _utc_now_iso(),
            self.source,
            self.wake_latency_ms,
            self.stt_text or None,
            self.stt_confidence,
            self.stt_ms,
            self.llm_ms,
            self.tool_ms or None,
            self.tts_ms,
            total_ms,
            self.model or None,
            self.tokens_in,
            self.tokens_out,
            self.cache_read_tokens,
            1 if self.interrupted else 0,
            1 if self.cancelled else 0,
            details_json,
        )

        for etype, payload in self._events:
            record_event(self.turn_id, etype, payload)

        if exc is not None:
            record_event(
                self.turn_id,
                "exception",
                {"type": type(exc).__name__, "message": str(exc)[:500]},
            )

        self._apply_signal_detections()
        return False

    def queue_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self._events.append((event_type, payload or {}))

    def add_tool_ms(self, ms: int) -> None:
        self.tool_ms += max(0, int(ms))

    def apply_usage(self, usage: Any) -> None:
        if usage is None:
            return
        self.tokens_in = getattr(usage, "input_tokens", None)
        self.tokens_out = getattr(usage, "output_tokens", None)
        cache = getattr(usage, "cache_read_input_tokens", None)
        if cache is None:
            cache = getattr(usage, "cache_creation_input_tokens", None)
        self.cache_read_tokens = cache

    def _apply_signal_detections(self) -> None:
        text = (self.stt_text or "").strip()
        prev_id, prev_text = _last_turn_text(self.session_id)
        if text:
            history = _recent_turn_texts(self.session_id, limit=4)
            if detect_repeat_request(history, text):
                self.queue_event("repeat_request", {"text_preview": text[:200]})
            if prev_id and prev_text:
                kind = detect_correction(prev_text, text)
                if kind:
                    _enqueue(
                        "correction",
                        str(uuid.uuid4()),
                        self.turn_id,
                        prev_id,
                        kind,
                    )
                    self.queue_event("correction", {"kind": kind, "prev_turn_id": prev_id})
            hist = _session_history.setdefault(self.session_id, [])
            hist.append(text)
            if len(hist) > 20:
                del hist[:-20]
            _session_last_turn[self.session_id] = (self.turn_id, text)
