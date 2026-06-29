"""Tests for orchestrator/session.py — Session lifecycle and SessionStore."""

from __future__ import annotations

import threading
import time

import pytest

from orchestrator.session import LaneType, Session, SessionState, SessionStore
from orchestrator.types import CommandSource, Turn


# ── Session dataclass ────────────────────────────────────────────────────────

def _make_session(**kw) -> Session:
    defaults = dict(
        id="test-session-id",
        lane=LaneType.VOICE,
        source=CommandSource.VOICE,
        created_at=time.time(),
        last_active_at=time.time(),
        state=SessionState.ACTIVE,
    )
    defaults.update(kw)
    return Session(**defaults)


def test_session_defaults():
    s = _make_session()
    assert s.id == "test-session-id"
    assert s.lane == LaneType.VOICE
    assert s.state == SessionState.ACTIVE
    assert s.turns == []
    assert s.metadata == {}


def test_session_add_turn_updates_last_active():
    s = _make_session()
    before = s.last_active_at
    time.sleep(0.02)
    turn = Turn(session_id=s.id, reply="hello")
    s.add_turn(turn)
    assert s.last_active_at > before
    assert len(s.turns) == 1


def test_session_touch_updates_last_active():
    s = _make_session()
    before = s.last_active_at
    time.sleep(0.02)
    s.touch()
    assert s.last_active_at > before


def test_session_is_not_expired_within_timeout():
    s = _make_session()
    assert not s.is_expired(timeout_sec=60.0)


def test_session_is_expired_past_timeout():
    past = time.time() - 200
    s = _make_session(last_active_at=past)
    assert s.is_expired(timeout_sec=60.0)


def test_session_close_sets_closed():
    s = _make_session()
    assert s.state == SessionState.ACTIVE
    s.close()
    assert s.state == SessionState.CLOSED


def test_session_to_dict_has_expected_keys():
    s = _make_session()
    d = s.to_dict()
    assert d["id"] == "test-session-id"
    assert d["lane"] == "voice"
    assert d["state"] == "active"
    assert "turn_count" in d
    assert "age_sec" in d
    assert "idle_sec" in d


# ── SessionStore ─────────────────────────────────────────────────────────────

def test_session_store_create_returns_active_session():
    store = SessionStore()
    s = store.create(LaneType.VOICE, CommandSource.VOICE)
    assert s.state == SessionState.ACTIVE
    assert s.lane == LaneType.VOICE
    assert s.id  # uuid not empty


def test_session_store_get_returns_same_session():
    store = SessionStore()
    s = store.create(LaneType.VOICE, CommandSource.VOICE)
    got = store.get(s.id)
    assert got is s


def test_session_store_get_missing_returns_none():
    store = SessionStore()
    assert store.get("nonexistent-id") is None


def test_session_store_close_marks_closed():
    store = SessionStore()
    s = store.create(LaneType.VOICE, CommandSource.VOICE)
    store.close(s.id)
    assert s.state == SessionState.CLOSED


def test_session_store_close_missing_is_noop():
    store = SessionStore()
    store.close("bogus-id")  # must not raise


def test_session_store_get_active_returns_non_closed():
    store = SessionStore()
    s = store.create(LaneType.VOICE, CommandSource.VOICE)
    result = store.get_active(LaneType.VOICE)
    assert result is s


def test_session_store_get_active_ignores_closed():
    store = SessionStore()
    s = store.create(LaneType.VOICE, CommandSource.VOICE)
    store.close(s.id)
    assert store.get_active(LaneType.VOICE) is None


def test_session_store_get_active_ignores_other_lane():
    store = SessionStore()
    store.create(LaneType.BACKGROUND, CommandSource.SCHEDULE)
    assert store.get_active(LaneType.VOICE) is None


def test_session_store_all_active_excludes_closed():
    store = SessionStore()
    s1 = store.create(LaneType.VOICE, CommandSource.VOICE)
    s2 = store.create(LaneType.BACKGROUND, CommandSource.SCHEDULE)
    store.close(s1.id)
    active = store.all_active()
    ids = {s.id for s in active}
    assert s1.id not in ids
    assert s2.id in ids


def test_session_store_close_idle_removes_expired():
    store = SessionStore()
    s = store.create(LaneType.VOICE, CommandSource.VOICE)
    # Backdate last_active_at to simulate expiry
    s.last_active_at = time.time() - 700
    count = store.close_idle(older_than_sec=600)
    assert count == 1
    assert s.state == SessionState.CLOSED


def test_session_store_close_idle_keeps_fresh():
    store = SessionStore()
    store.create(LaneType.VOICE, CommandSource.VOICE)
    count = store.close_idle(older_than_sec=600)
    assert count == 0


def test_session_store_mark_idle_transitions_state():
    store = SessionStore()
    s = store.create(LaneType.VOICE, CommandSource.VOICE)
    store.mark_idle(s.id)
    assert s.state == SessionState.IDLE


def test_session_store_mark_active_from_idle():
    store = SessionStore()
    s = store.create(LaneType.VOICE, CommandSource.VOICE)
    store.mark_idle(s.id)
    store.mark_active(s.id)
    assert s.state == SessionState.ACTIVE


# ── Thread safety ────────────────────────────────────────────────────────────

def test_session_store_thread_safe_create():
    """50 concurrent creates must produce exactly 50 distinct sessions."""
    store = SessionStore()
    results: list[Session] = []
    errors: list[Exception] = []

    def worker():
        try:
            s = store.create(LaneType.VOICE, CommandSource.VOICE)
            results.append(s)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, f"errors: {errors}"
    assert len(results) == 50
    ids = {s.id for s in results}
    assert len(ids) == 50, "all session IDs must be unique"
