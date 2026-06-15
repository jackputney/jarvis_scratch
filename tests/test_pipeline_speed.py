"""Pipeline speed features — sentence emitter, hotwords, energy VAD."""

import pipeline


def test_sentence_emitter_splits_on_period():
    chunks: list[str] = []
    emitter = pipeline._SentenceEmitter(chunks.append)
    emitter.feed("Hello there. And ")
    emitter.feed("goodbye!")
    emitter.flush()
    assert chunks == ["Hello there.", "And goodbye!"]


def test_sentence_emitter_soft_cap():
    chunks: list[str] = []
    emitter = pipeline._SentenceEmitter(chunks.append)
    long_run = "word " * 50
    emitter.feed(long_run)
    emitter.flush()
    assert len(chunks) >= 2
    assert "".join(chunks).startswith("word")


def test_is_speech_energy_detects_loud_frame():
    import numpy as np

    loud = (np.ones(480, dtype=np.int16) * 5000).tobytes()
    quiet = (np.ones(480, dtype=np.int16) * 50).tobytes()
    assert pipeline._is_speech_energy(loud) is True
    assert pipeline._is_speech_energy(quiet) is False


def test_stt_hotwords_cache(monkeypatch):
    pipeline._hotwords_cache["ts"] = 0.0
    pipeline._hotwords_cache["value"] = ""
    calls = {"n": 0}

    def fake_names():
        calls["n"] += 1
        return ["Alice", "Bob"]

    monkeypatch.setattr("tools.google_contacts.get_contact_names", fake_names)
    first = pipeline._stt_hotwords()
    second = pipeline._stt_hotwords()
    assert first == "Alice, Bob"
    assert second == "Alice, Bob"
    assert calls["n"] == 1


def test_build_system_blocks_has_cache_control():
    from config import Config

    blocks = pipeline._build_system_blocks(Config())
    assert len(blocks) == 2
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "Jarvis" in blocks[0]["text"]
