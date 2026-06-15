"""Phase 1 orchestrator — queue, ordering, overflow, stale-drop, cancel, speak."""

import threading
import time

import pytest

from orchestrator.core import Orchestrator
from orchestrator.events import EventBus
from orchestrator.types import Command, CommandSource, JobState


class _FakeCfg:
    cartesia_voice_id = "voice-x"


@pytest.fixture
def make_orch():
    created: list[Orchestrator] = []

    def _factory(process_query, speak=None, **kwargs):
        ev = threading.Event()
        orch = Orchestrator(
            bus=EventBus(),
            process_query=process_query,
            speak=speak,
            config_loader=_FakeCfg,
            interrupt_event=ev,
            request_interrupt=ev.set,
            clear_interrupt=ev.clear,
            **kwargs,
        )
        created.append(orch)
        return orch, ev

    yield _factory
    for orch in created:
        orch.shutdown()


def test_voice_command_runs_and_is_spoken(make_orch):
    spoken: list[str] = []
    orch, _ev = make_orch(
        lambda text, cfg, on_state=None, speak=False: {"reply": "hi there", "model": "m"},
        speak=lambda t, **kw: spoken.append(t),
    )
    sub = orch.submit(Command("hello", CommandSource.VOICE, speak=True))
    job = orch.wait(sub.job_id, timeout=5)
    assert job is not None
    assert job.state == JobState.DONE
    assert job.reply == "hi there"
    assert spoken == ["hi there"]


def test_dashboard_command_is_not_spoken(make_orch):
    spoken: list[str] = []
    orch, _ev = make_orch(
        lambda text, cfg, on_state=None, speak=False: {"reply": "on screen"},
        speak=lambda t, **kw: spoken.append(t),
    )
    job = orch.wait(
        orch.submit(Command("hi", CommandSource.DASHBOARD, speak=False)).job_id,
        timeout=5,
    )
    assert job.state == JobState.DONE
    assert spoken == []


def test_warning_is_prepended_when_spoken(make_orch):
    spoken: list[str] = []
    orch, _ev = make_orch(
        lambda text, cfg, on_state=None, speak=False: {"reply": "the answer", "warning": "Heads up."},
        speak=lambda t, **kw: spoken.append(t),
    )
    orch.wait(orch.submit(Command("q", CommandSource.VOICE, speak=True)).job_id, timeout=5)
    assert spoken == ["Heads up. the answer"]


def test_queue_preserves_order(make_orch):
    order: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def pq(text, cfg, on_state=None, speak=False):
        order.append(text)
        if text == "first":
            started.set()
            release.wait(timeout=5)
        return {"reply": text}

    orch, _ev = make_orch(pq)
    orch.submit(Command("first", CommandSource.VOICE, speak=False))
    assert started.wait(timeout=2)
    r2 = orch.submit(Command("c2", CommandSource.VOICE, speak=False))
    r3 = orch.submit(Command("c3", CommandSource.VOICE, speak=False))
    r4 = orch.submit(Command("c4", CommandSource.VOICE, speak=False))
    assert all(r.accepted for r in (r2, r3, r4))
    release.set()
    orch.wait(r4.job_id, timeout=5)
    assert order == ["first", "c2", "c3", "c4"]


def test_overflow_is_rejected_busy(make_orch):
    started = threading.Event()
    release = threading.Event()

    def pq(text, cfg, on_state=None, speak=False):
        if text == "first":
            started.set()
            release.wait(timeout=5)
        return {"reply": text}

    orch, _ev = make_orch(pq, max_queue_depth=3)
    orch.submit(Command("first", CommandSource.VOICE, speak=False))
    assert started.wait(timeout=2)
    # 3 may wait behind the running job; the 4th overflows.
    for name in ("c2", "c3", "c4"):
        assert orch.submit(Command(name, CommandSource.VOICE, speak=False)).accepted
    overflow = orch.submit(Command("c5", CommandSource.VOICE, speak=False))
    assert overflow.accepted is False
    assert overflow.reason == "busy"
    release.set()


def test_stale_command_is_dropped(make_orch):
    ran: list[str] = []
    orch, _ev = make_orch(lambda text, cfg, on_state=None, speak=False: ran.append(text) or {"reply": text})
    stale = Command("old", CommandSource.VOICE, speak=False, created_at=time.time() - 120)
    job = orch.wait(orch.submit(stale).job_id, timeout=3)
    assert job.state == JobState.CANCELLED
    assert job.error == "stale"
    assert ran == []


def test_cancel_clears_queue_and_interrupts(make_orch):
    started = threading.Event()
    release = threading.Event()

    def pq(text, cfg, on_state=None, speak=False):
        if text == "first":
            started.set()
            release.wait(timeout=5)
        return {"reply": text}

    orch, ev = make_orch(pq)
    s1 = orch.submit(Command("first", CommandSource.VOICE, speak=False))
    assert started.wait(timeout=2)
    s2 = orch.submit(Command("second", CommandSource.VOICE, speak=False))

    orch.cancel_current()
    assert ev.is_set()  # request_interrupt fired

    j2 = orch.wait(s2.job_id, timeout=3)
    assert j2.state == JobState.CANCELLED  # queued command dropped

    release.set()
    j1 = orch.wait(s1.job_id, timeout=5)
    assert j1.state == JobState.CANCELLED  # running turn observed the interrupt


def test_busy_result_marks_job_failed(make_orch):
    orch, _ev = make_orch(
        lambda text, cfg, on_state=None, speak=False: {"reply": "busy", "busy": True}
    )
    job = orch.wait(
        orch.submit(Command("x", CommandSource.DASHBOARD, speak=False)).job_id, timeout=3
    )
    assert job.state == JobState.FAILED
    assert job.error == "busy"


def test_pipeline_state_events_emitted(make_orch):
    seen: list[str] = []
    orch, _ev = make_orch(lambda text, cfg, on_state=None, speak=False: {"reply": "ok"})
    orch._bus.subscribe(
        lambda event, payload: seen.append(payload["state"])
        if event == "pipeline.state" else None
    )
    orch.wait(orch.submit(Command("q", CommandSource.VOICE, speak=False)).job_id, timeout=5)
    assert "THINKING" in seen
    assert "IDLE" in seen
