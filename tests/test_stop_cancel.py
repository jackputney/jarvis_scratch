"""Stop button / cancel_current — TTS, Claude stream, state, and trace."""

from __future__ import annotations

import threading
import time

import events
import pipeline
from orchestrator.core import Orchestrator
from orchestrator.events import EventBus
from orchestrator.types import Command, CommandSource, JobState


class _FakeCfg:
    cartesia_voice_id = "voice-x"
    streaming_tts = False
    claude_model_fast = "claude-haiku-4-5"


def _make_orch(process_query, **kwargs):
    ev = threading.Event()
    kwargs.setdefault("config_loader", _FakeCfg)
    bus = EventBus()

    def _sync_legacy(event: str, payload: dict) -> None:
        if event == "pipeline.state":
            events.set_pipeline_state(payload.get("state", "IDLE"))

    bus.subscribe(_sync_legacy)
    orch = Orchestrator(
        bus=bus,
        process_query=process_query,
        speak=lambda *_a, **_k: None,
        interrupt_event=pipeline._interrupt,
        request_interrupt=pipeline.request_interrupt,
        clear_interrupt=pipeline._clear_interrupt,
        **kwargs,
    )
    return orch, ev


def test_cancel_current_sets_idle_immediately():
    started = threading.Event()
    release = threading.Event()
    states: list[str] = []

    def pq(text, cfg, on_state=None, speak=False, on_sentence=None):
        if on_state:
            on_state("THINKING")
        started.set()
        release.wait(timeout=5)
        return {"reply": "late"}

    pipeline._clear_interrupt()
    events.set_pipeline_state("IDLE")
    orch, _ = _make_orch(pq)
    orch.set_state_callback(states.append)
    sub = orch.submit(Command("hold", CommandSource.DASHBOARD, speak=False))
    assert started.wait(timeout=2)

    t0 = time.monotonic()
    orch.cancel_current()
    elapsed_ms = (time.monotonic() - t0) * 1000

    assert events.get_state()["pipeline_state"] == "IDLE"
    assert elapsed_ms < 500
    assert pipeline.interrupt_requested()

    release.set()
    job = orch.wait(sub.job_id, timeout=5)
    assert job is not None
    assert job.state == JobState.CANCELLED
    orch.shutdown()


def test_cancel_marks_active_turn_trace_cancelled(monkeypatch):
    from improvement.trace import flush_writes, get_active_trace, reset_writer_for_tests
    from memory.db import init_db

    reset_writer_for_tests()
    init_db()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    started = threading.Event()
    release = threading.Event()
    traces: list = []

    def pq(text, cfg, on_state=None, speak=False, on_sentence=None):
        started.set()
        active = get_active_trace()
        if active is not None:
            traces.append(active)
        release.wait(timeout=5)
        return {"reply": ""}

    pipeline._clear_interrupt()
    orch, _ = _make_orch(pq)
    sub = orch.submit(Command("trace", CommandSource.VOICE, speak=False))
    assert started.wait(timeout=2)
    assert traces
    orch.cancel_current()
    assert traces[0].cancelled is True
    release.set()
    orch.wait(sub.job_id, timeout=5)
    flush_writes()
    orch.shutdown()


def test_cancel_during_slow_claude_returns_within_500ms():
    """Mock a long Claude response; Stop must reach IDLE quickly."""
    started = threading.Event()
    release = threading.Event()

    def pq(text, cfg, on_state=None, speak=False, on_sentence=None):
        if on_state:
            on_state("THINKING")
        started.set()
        release.wait(timeout=5)
        return {"reply": ""}

    pipeline._clear_interrupt()
    events.set_pipeline_state("IDLE")
    orch, _ = _make_orch(pq)
    sub = orch.submit(Command("slow", CommandSource.DASHBOARD, speak=False))
    assert started.wait(timeout=2)
    assert events.get_state()["pipeline_state"] == "THINKING"

    t0 = time.monotonic()
    orch.cancel_current()
    assert (time.monotonic() - t0) * 1000 < 500
    assert events.get_state()["pipeline_state"] == "IDLE"

    release.set()
    job = orch.wait(sub.job_id, timeout=5)
    assert job.state == JobState.CANCELLED
    orch.shutdown()
