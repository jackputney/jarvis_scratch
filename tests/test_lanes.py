"""Tests for orchestrator/lanes.py — VoiceLane, BackgroundLane, LaneManager."""

from __future__ import annotations

import threading
import time
import uuid
from unittest.mock import MagicMock

import pytest

from orchestrator.events import EventBus
from orchestrator.lanes import BackgroundLane, LaneManager, VoiceLane
from orchestrator.session import LaneType, SessionState, SessionStore
from orchestrator.types import Command, CommandSource, SubmitResult


# ── helpers ──────────────────────────────────────────────────────────────────

def _voice_cmd(text: str = "hello") -> Command:
    return Command(text=text, source=CommandSource.VOICE)


def _mock_orchestrator(accepted: bool = True) -> MagicMock:
    orc = MagicMock()
    job = MagicMock()
    job.session_id = None
    orc.get_job.return_value = job
    orc.queue_depth.return_value = 0
    orc.submit.return_value = SubmitResult(accepted=accepted, job_id=str(uuid.uuid4()))
    return orc


# ── VoiceLane ────────────────────────────────────────────────────────────────

def test_voice_lane_submit_creates_new_session():
    store = SessionStore()
    bus = EventBus()
    orc = _mock_orchestrator()
    lane = VoiceLane(orchestrator=orc, store=store, bus=bus)

    result = lane.submit(_voice_cmd())

    assert result.accepted
    sessions = store.all_active()
    assert len(sessions) == 1
    assert sessions[0].lane == LaneType.VOICE


def test_voice_lane_submit_continues_idle_session():
    store = SessionStore()
    bus = EventBus()
    orc = _mock_orchestrator()
    lane = VoiceLane(orchestrator=orc, store=store, bus=bus)

    # First submit creates session, second should continue it
    lane.submit(_voice_cmd("first"))
    first_sessions = store.all_active()
    first_id = first_sessions[0].id

    store.mark_idle(first_id)
    lane.submit(_voice_cmd("second"))

    active = store.all_active()
    # Still one session — not two
    assert len(active) == 1
    assert active[0].id == first_id
    assert active[0].state == SessionState.ACTIVE


def test_voice_lane_submit_creates_new_when_expired():
    store = SessionStore()
    bus = EventBus()
    orc = _mock_orchestrator()
    lane = VoiceLane(orchestrator=orc, store=store, bus=bus)
    lane.idle_timeout_sec = 0.01  # very short timeout

    lane.submit(_voice_cmd("first"))
    first_id = store.all_active()[0].id
    store.mark_idle(first_id)

    time.sleep(0.05)  # let the session expire
    lane.submit(_voice_cmd("second"))

    active = store.all_active()
    active_ids = {s.id for s in active}
    # Old session closed, new session created
    assert first_id not in active_ids or store.get(first_id).state == SessionState.CLOSED


def test_voice_lane_active_session_returns_non_closed():
    store = SessionStore()
    bus = EventBus()
    orc = _mock_orchestrator()
    lane = VoiceLane(orchestrator=orc, store=store, bus=bus)

    assert lane.active_session() is None
    lane.submit(_voice_cmd())
    assert lane.active_session() is not None


def test_voice_lane_is_busy_reflects_orchestrator():
    store = SessionStore()
    bus = EventBus()
    orc = _mock_orchestrator()
    orc.queue_depth.return_value = 0
    lane = VoiceLane(orchestrator=orc, store=store, bus=bus)
    assert not lane.is_busy()

    orc.queue_depth.return_value = 1
    assert lane.is_busy()


def test_voice_lane_emits_session_created_event():
    store = SessionStore()
    bus = EventBus()
    orc = _mock_orchestrator()
    lane = VoiceLane(orchestrator=orc, store=store, bus=bus)

    events: list[tuple[str, dict]] = []
    bus.subscribe(lambda e, p: events.append((e, p)))

    lane.submit(_voice_cmd())
    event_names = [e for e, _ in events]
    assert "session.created" in event_names


def test_voice_lane_emits_session_continued_event():
    store = SessionStore()
    bus = EventBus()
    orc = _mock_orchestrator()
    lane = VoiceLane(orchestrator=orc, store=store, bus=bus)

    events: list[tuple[str, dict]] = []
    bus.subscribe(lambda e, p: events.append((e, p)))

    lane.submit(_voice_cmd("first"))
    first_id = store.all_active()[0].id
    store.mark_idle(first_id)

    events.clear()
    lane.submit(_voice_cmd("second"))
    event_names = [e for e, _ in events]
    assert "session.continued" in event_names


# ── BackgroundLane ───────────────────────────────────────────────────────────

def test_background_lane_submit_runs_in_separate_thread():
    store = SessionStore()
    bus = EventBus()
    bg = BackgroundLane(store=store, bus=bus)
    cmd = Command(text="background task", source=CommandSource.SCHEDULE)

    caller_thread = threading.current_thread()
    worker_threads: list[threading.Thread] = []

    done = threading.Event()

    def _cb(job_id, result):
        worker_threads.append(threading.current_thread())
        done.set()

    result = bg.submit(cmd)
    bg.on_complete(result.job_id, _cb)
    done.wait(timeout=3.0)

    assert result.accepted
    assert result.job_id
    bg.shutdown(wait=True)


def test_background_lane_creates_background_session():
    store = SessionStore()
    bus = EventBus()
    bg = BackgroundLane(store=store, bus=bus)
    cmd = Command(text="bg task", source=CommandSource.SCHEDULE)

    done = threading.Event()
    bus.subscribe(lambda e, p: done.set() if e == "lane.background.complete" else None)

    bg.submit(cmd)
    done.wait(timeout=3.0)
    bg.shutdown(wait=True)

    # Background session should be closed after completion
    bg_sessions = [s for s in store._sessions.values() if s.lane == LaneType.BACKGROUND]
    assert all(s.state == SessionState.CLOSED for s in bg_sessions)


def test_background_lane_emits_queued_event():
    store = SessionStore()
    bus = EventBus()
    bg = BackgroundLane(store=store, bus=bus)

    events: list[str] = []
    bus.subscribe(lambda e, p: events.append(e))

    cmd = Command(text="bg task", source=CommandSource.SCHEDULE)
    bg.submit(cmd)
    bg.shutdown(wait=True)

    assert "lane.background.queued" in events


def test_background_lane_is_busy_while_running():
    store = SessionStore()
    bus = EventBus()
    bg = BackgroundLane(store=store, bus=bus)

    started = threading.Event()
    block = threading.Event()

    original_submit = bg._pool.submit

    def slow_fn():
        started.set()
        block.wait(timeout=3.0)

    future = bg._pool.submit(slow_fn)
    started.wait(timeout=2.0)
    with bg._lock:
        bg._jobs["fake-job"] = future

    assert bg.is_busy()
    block.set()
    future.result(timeout=2.0)
    bg.shutdown(wait=True)


# ── LaneManager ─────────────────────────────────────────────────────────────

def test_lane_manager_routes_voice_to_voice():
    store = SessionStore()
    bus = EventBus()
    orc = _mock_orchestrator()
    voice = VoiceLane(orchestrator=orc, store=store, bus=bus)
    bg = BackgroundLane(store=store, bus=bus)
    mgr = LaneManager(voice=voice, background=bg)

    assert mgr.route(CommandSource.VOICE) == LaneType.VOICE
    assert mgr.route(CommandSource.DASHBOARD) == LaneType.VOICE


def test_lane_manager_routes_schedule_to_background():
    store = SessionStore()
    bus = EventBus()
    orc = _mock_orchestrator()
    voice = VoiceLane(orchestrator=orc, store=store, bus=bus)
    bg = BackgroundLane(store=store, bus=bus)
    mgr = LaneManager(voice=voice, background=bg)

    assert mgr.route(CommandSource.SCHEDULE) == LaneType.BACKGROUND
    assert mgr.route(CommandSource.WEBHOOK) == LaneType.BACKGROUND
