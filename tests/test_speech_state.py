"""Speech state machine and VAD barge-in tests."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import events
from config import Config
from pipeline import _barge_energy_threshold, wake_detection_paused
from voice.speech_state import (
    BARGEIN_GRACE_SEC,
    BargeInGate,
    SpeechPhase,
    WAKE_DETECTION_OFF_STATES,
    transition,
)


def test_wake_detection_off_includes_followup_window():
    assert "FOLLOWUP_WINDOW" in WAKE_DETECTION_OFF_STATES


def test_wake_detection_paused_during_followup():
    events.set_pipeline_state("FOLLOWUP_WINDOW")
    assert wake_detection_paused(threading.Event(), threading.Event()) is True


def test_barge_energy_threshold_scales_with_config():
    cfg = Config()
    cfg.barge_in_threshold = 0.5
    baseline = _barge_energy_threshold(cfg)
    cfg.barge_in_threshold = 1.0
    assert _barge_energy_threshold(cfg) > baseline


def test_barge_in_gate_reset():
    gate = BargeInGate()
    gate.armed.set()
    gate.triggered.set()
    gate.speech_frames = 3
    gate.reset()
    assert not gate.armed.is_set()
    assert not gate.triggered.is_set()
    assert gate.speech_frames == 0


def test_transition_logs_reason(caplog):
    import logging

    seen: list[str] = []

    def _set(name: str) -> None:
        seen.append(name)

    with caplog.at_level(logging.INFO, logger="jarvis.voice"):
        transition(_set, SpeechPhase.LISTENING, reason="barge-in")
    assert seen == ["LISTENING"]
    assert any("barge-in" in r.message for r in caplog.records)


def test_wait_for_job_arms_barge_after_grace(monkeypatch, caplog):
    import logging

    import pipeline

    gate = BargeInGate()
    cfg = Config()
    cfg.barge_in_enabled = True

    job = MagicMock()
    job.done_event.is_set.return_value = False

    orchestrator = MagicMock()
    orchestrator.wait.return_value = job

    tick = {"n": 0}

    def monotonic() -> float:
        tick["n"] += 1
        if tick["n"] <= 2:
            return 0.0
        if tick["n"] == 3:
            return BARGEIN_GRACE_SEC + 0.05
        return 999.0

    monkeypatch.setattr(pipeline.time, "monotonic", monotonic)
    events.set_pipeline_state("SPEAKING")

    with caplog.at_level(logging.DEBUG, logger="jarvis.pipeline"):
        pipeline._wait_for_job_with_bargein(
            orchestrator,
            "job-1",
            cfg,
            threading.Event(),
            __import__("queue").Queue(),
            threading.Event(),
            threading.Event(),
            gate,
            timeout=30.0,
        )
    assert any("VAD barge-in armed" in r.message for r in caplog.records)


def test_barge_in_grace_is_800ms():
    assert BARGEIN_GRACE_SEC == 0.8
