"""Voice pipeline reliability — config tuning and follow-up helpers."""

from __future__ import annotations

from config import Config
from pipeline import _followup_wait_frames, _answer_wait_frames, FRAME_DURATION_MS
from tts.cartesia import FRAME_BYTES, _silence_pcm, _trailing_silence_ms


def test_config_voice_tuning_defaults():
    cfg = Config()
    assert cfg.wakeword_threshold == 0.5
    assert cfg.barge_in_threshold == 0.5
    assert cfg.barge_in_hits == 2
    assert cfg.followup_listen_sec == 5
    assert cfg.followup_vad_silence_ms == 900
    assert cfg.tts_trailing_silence_ms == 100


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
