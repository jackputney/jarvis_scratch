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
    assert "escalate" in blocks[0]["text"].lower()


def test_call_claude_escalates_model(monkeypatch, temp_env):
    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    pipeline._interrupt.clear()

    class EscalateBlock:
        type = "tool_use"
        id = "tu_esc"
        name = "escalate"
        input = {}

    class EscalateResponse:
        content = [EscalateBlock()]
        usage = None

    class AnswerBlock:
        type = "text"
        text = "Deep answer."

    class FinalResponse:
        content = [AnswerBlock()]
        usage = None

    calls: list[str] = []

    class FakeStream:
        def __init__(self, final):
            self._final = final

        @property
        def text_stream(self):
            return iter([])

        def get_final_message(self):
            return self._final

    class FakeCM:
        def __init__(self, final):
            self._stream = FakeStream(final)

        def __enter__(self):
            return self._stream

        def __exit__(self, *exc):
            return False

    class FakeMessages:
        def stream(self, **kwargs):
            calls.append(kwargs["model"])
            final = EscalateResponse() if len(calls) == 1 else FinalResponse()
            return FakeCM(final)

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: FakeClient())

    from config import Config

    cfg = Config(claude_model_fast="claude-haiku-4-5", claude_model_smart="claude-sonnet-4-6")
    reply, model, _cost, _spoken = pipeline._call_claude("plan my week", cfg)
    assert calls == ["claude-haiku-4-5", "claude-sonnet-4-6"]
    assert model == "claude-sonnet-4-6"
    assert reply == "Deep answer."
