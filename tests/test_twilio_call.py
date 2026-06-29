"""Tests for adapters/twilio_call.py — utterance VAD and phone turn routing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from adapters.twilio_call import (
    MulawUtteranceDetector,
    release_phone_call,
    run_phone_turn,
    try_acquire_phone_call,
)
from config import Config


def test_try_acquire_phone_call_single_active():
    release_phone_call("")
    assert try_acquire_phone_call("CA111")
    assert not try_acquire_phone_call("CA222")
    release_phone_call("CA111")
    assert try_acquire_phone_call("CA222")


def test_mulaw_detector_emits_after_speech_and_silence(monkeypatch):
    cfg = Config()
    cfg.vad_silence_ms = 300
    cfg.vad_min_capture_ms = 300
    detector = MulawUtteranceDetector(cfg)
    speaking = [False]

    def fake_is_speech(_frame, _cfg, **kwargs):
        return speaking[0]

    monkeypatch.setattr("adapters.twilio_call.frame_is_speech", fake_is_speech)

    chunk = b"\xff" * 240
    speaking[0] = True
    for _ in range(18):
        assert detector.feed(chunk) is None
    speaking[0] = False
    utterance = None
    for _ in range(25):
        utterance = detector.feed(chunk)
        if utterance:
            break
    assert utterance is not None
    assert len(utterance) > 0


def test_run_phone_turn_uses_voice_lane(monkeypatch):
    cfg = Config()
    job = MagicMock()
    job.reply = "On it."
    job.session_id = "sess-abc"
    job.capped = False

    orch = MagicMock()
    orch.wait.return_value = job

    voice_lane = MagicMock()
    voice_lane.submit.return_value = MagicMock(accepted=True, job_id="job-1")

    lane_manager = MagicMock()
    lane_manager.voice = voice_lane

    monkeypatch.setattr("orchestrator.runtime.get_lane_manager", lambda: lane_manager)
    monkeypatch.setattr("orchestrator.runtime.get_orchestrator", lambda: orch)

    out = run_phone_turn("check my calendar", cfg, session_id=None)
    assert out["reply"] == "On it."
    assert out["session_id"] == "sess-abc"
    voice_lane.submit.assert_called_once()
    assert voice_lane.submit.call_args[0][0].speak is False
