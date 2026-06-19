"""Voice pipeline reliability — config tuning, echo guard, and follow-up helpers."""

from __future__ import annotations

import inspect
import threading

import events
from config import Config
from pipeline import (
    _answer_wait_frames,
    _followup_wait_frames,
    _ensure_wake_model,
    wake_detection_paused,
    FRAME_DURATION_MS,
)
from tts.cartesia import FRAME_BYTES, _silence_pcm, _trailing_silence_ms


def test_config_voice_tuning_defaults():
    cfg = Config()
    assert cfg.wakeword_threshold == 0.5
    assert cfg.barge_in_threshold == 0.42
    assert cfg.barge_in_hits == 1
    assert cfg.followup_vad_silence_ms == 600
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
