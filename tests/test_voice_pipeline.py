"""Voice pipeline reliability — config tuning, echo guard, and follow-up helpers."""

from __future__ import annotations

import inspect
import queue
import threading

import events
from config import Config
from pipeline import (
    MAX_FOLLOWUP_MISSES,
    _answer_wait_frames,
    _await_followup_utterance,
    _followup_wait_frames,
    _ensure_wake_model,
    _is_end_phrase,
    wake_detection_paused,
    FRAME_DURATION_MS,
)
from tts.cartesia import FRAME_BYTES, _silence_pcm, _trailing_silence_ms


def test_config_voice_tuning_defaults():
    cfg = Config()
    assert cfg.barge_in_threshold == 0.48
    assert cfg.barge_in_hits == 2
    assert cfg.followup_listen_sec == 10
    assert cfg.followup_vad_silence_ms == 1100
    assert cfg.tts_trailing_silence_ms == 80


def test_config_wakeword_model_default():
    cfg = Config()
    assert cfg.wakeword_model == "hey_jarvis"


def test_config_followup_window_seconds_alias(temp_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cfg = Config.update_persisted({"followup_window_seconds": 8})
    assert cfg.followup_listen_sec == 8


def test_config_persists_voice_tuning(temp_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cfg = Config.update_persisted({
        "wakeword_threshold": 0.45,
        "barge_in_threshold": 0.6,
        "barge_in_hits": 3,
        "followup_listen_sec": 7,
        "vad_silence_ms": 1200,
    })
    assert cfg.wakeword_threshold == 0.45
    assert cfg.barge_in_threshold == 0.6
    assert cfg.barge_in_hits == 3
    assert cfg.followup_listen_sec == 7
    assert cfg.vad_silence_ms == 1200


def test_followup_wait_frames_from_config():
    cfg = Config()
    cfg.followup_listen_sec = 5
    frames = _followup_wait_frames(cfg)
    assert frames == int(5000 / FRAME_DURATION_MS)


def test_answer_wait_at_least_followup():
    cfg = Config()
    cfg.followup_listen_sec = 5
    assert _answer_wait_frames(cfg) >= _followup_wait_frames(cfg)


def test_silence_pcm_is_sample_aligned():
    chunk = _silence_pcm(150)
    assert len(chunk) > 0
    assert len(chunk) % FRAME_BYTES == 0


def test_trailing_silence_ms_reads_config(temp_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    Config.update_persisted({"tts_trailing_silence_ms": 180})
    assert _trailing_silence_ms() == 180


def test_audio_loop_feeds_predict_frombuffer_not_struct_unpack():
    """F3 — predict() must receive a numpy int16 buffer, not struct.unpack tuples."""
    import pipeline

    src = inspect.getsource(pipeline._audio_loop)
    assert "np.frombuffer" in src
    assert "struct.unpack" not in src


def test_wake_detection_paused_during_speaking():
    """F5 — no wake predict while Jarvis is speaking (prevents self-trigger)."""
    events.set_pipeline_state("SPEAKING")
    capturing = threading.Event()
    paused = threading.Event()
    assert wake_detection_paused(capturing, paused) is True


def test_wake_detection_paused_during_listening_state():
    events.set_pipeline_state("LISTENING")
    assert wake_detection_paused(threading.Event(), threading.Event()) is True


def test_wake_detection_runs_when_idle():
    events.set_pipeline_state("IDLE")
    assert wake_detection_paused(threading.Event(), threading.Event()) is False


def test_wake_detection_paused_when_capture_flag_set():
    events.set_pipeline_state("IDLE")
    capturing = threading.Event()
    capturing.set()
    assert wake_detection_paused(capturing, threading.Event()) is True


def test_ensure_wake_model_raises_clearly_when_offline(monkeypatch):
    """F2 — first-run download failure must surface an actionable error."""
    import types

    import pytest

    import pipeline

    fake_models = {"hey_jarvis": {"model_path": "/fake/hey_jarvis_v0.1.tflite"}}
    oww_pkg = types.ModuleType("openwakeword")
    oww_pkg.MODELS = fake_models
    utils_mod = types.ModuleType("openwakeword.utils")

    def _fail_download(_names: list[str]) -> None:
        raise OSError("network unreachable")

    utils_mod.download_models = _fail_download
    monkeypatch.setitem(__import__("sys").modules, "openwakeword", oww_pkg)
    monkeypatch.setitem(__import__("sys").modules, "openwakeword.utils", utils_mod)
    monkeypatch.setattr(pipeline.os.path, "exists", lambda _p: False)

    with pytest.raises(RuntimeError, match="Could not download"):
        pipeline._ensure_wake_model("hey_jarvis")


def test_is_end_phrase():
    assert _is_end_phrase("that's all")
    assert _is_end_phrase("Thanks Jarvis!")
    assert _is_end_phrase("we're done")
    assert _is_end_phrase("that's all for now")
    assert not _is_end_phrase("open Spotify")
    assert not _is_end_phrase("that's all the apps")


def test_await_followup_utterance_succeeds_on_first_try(monkeypatch):
    pipeline = __import__("pipeline")
    pipeline._interrupt.clear()
    calls: list[int] = []

    def fake_capture(*_a, **_k):
        calls.append(1)
        return "follow up question"

    monkeypatch.setattr(pipeline, "_capture_and_transcribe", fake_capture)
    cfg = Config()
    q: queue.Queue[bytes] = queue.Queue()
    capturing = threading.Event()
    paused = threading.Event()
    wake = threading.Event()
    states: list[str] = []

    text = _await_followup_utterance(
        q, capturing, paused, cfg, states.append, wake, max_misses=3,
    )
    assert text == "follow up question"
    assert calls == [1]


def test_await_followup_utterance_forgives_transient_misses(monkeypatch):
    pipeline = __import__("pipeline")
    pipeline._interrupt.clear()
    results = [None, None, "third time's the charm"]

    def fake_capture(*_a, **_k):
        return results.pop(0)

    monkeypatch.setattr(pipeline, "_capture_and_transcribe", fake_capture)
    cfg = Config()
    q: queue.Queue[bytes] = queue.Queue()
    capturing = threading.Event()
    paused = threading.Event()
    wake = threading.Event()

    text = _await_followup_utterance(
        q, capturing, paused, cfg, lambda _s: None, wake, max_misses=3,
    )
    assert text == "third time's the charm"
    assert len(results) == 0


def test_await_followup_utterance_exits_after_max_misses(monkeypatch):
    pipeline = __import__("pipeline")
    pipeline._interrupt.clear()
    calls: list[int] = []

    def fake_capture(*_a, **_k):
        calls.append(1)
        return None

    monkeypatch.setattr(pipeline, "_capture_and_transcribe", fake_capture)
    cfg = Config()
    q: queue.Queue[bytes] = queue.Queue()
    capturing = threading.Event()
    paused = threading.Event()
    wake = threading.Event()

    text = _await_followup_utterance(
        q, capturing, paused, cfg, lambda _s: None, wake, max_misses=MAX_FOLLOWUP_MISSES,
    )
    assert text is None
    assert len(calls) == MAX_FOLLOWUP_MISSES


def test_await_followup_utterance_end_phrase(monkeypatch):
    pipeline = __import__("pipeline")
    pipeline._interrupt.clear()
    spoken: list[str] = []
    states: list[str] = []

    monkeypatch.setattr(pipeline, "_capture_and_transcribe", lambda *_a, **_k: "that's all")
    monkeypatch.setattr(pipeline, "speak", lambda msg: spoken.append(msg))

    cfg = Config()
    q: queue.Queue[bytes] = queue.Queue()
    capturing = threading.Event()
    paused = threading.Event()
    wake = threading.Event()

    text = _await_followup_utterance(
        q, capturing, paused, cfg, states.append, wake, max_misses=3,
    )
    assert text is None
    assert spoken == ["Okay."]
    assert states[-1] == "IDLE"
