"""Audio I/O adapter: VAD helpers and backend resolution (no hardware)."""

from __future__ import annotations

import adapters.audio_io as audio_io
from config import Config


def test_barge_energy_threshold_scales():
    cfg = Config()
    cfg.barge_in_threshold = 0.5
    baseline = audio_io.barge_energy_threshold(cfg)
    cfg.barge_in_threshold = 1.0
    assert audio_io.barge_energy_threshold(cfg) > baseline


def test_frame_is_speech_energy_fallback():
    import numpy as np

    loud = (np.ones(audio_io.FRAME_SIZE, dtype=np.int16) * 5000).tobytes()
    quiet = (np.ones(audio_io.FRAME_SIZE, dtype=np.int16) * 50).tobytes()
    cfg = Config()
    assert audio_io.frame_is_speech(loud, cfg) is True
    assert audio_io.frame_is_speech(quiet, cfg) is False


def test_resolve_backend_returns_mic_capture():
    audio_io._backend = None
    backend = audio_io.resolve_backend()
    assert backend.name == "mic"


def test_record_from_queue_interrupt_returns_empty(monkeypatch):
    import queue

    q: queue.Queue[bytes] = queue.Queue()
    monkeypatch.setattr("adapters.audio_io.is_speech_energy", lambda _d: True)
    q.put(b"\x00" * audio_io.FRAME_SIZE * 2)

    result = audio_io.record_from_queue(
        q,
        wait_for_speech_frames=100,
        interrupt_check=lambda: True,
    )
    assert result == b""
