"""STT adapter: backend resolution and fallback (no model loading)."""

from __future__ import annotations

import builtins

import adapters.stt as stt


def _reset_cache():
    stt._backend = None


def test_resolve_faster_backend():
    _reset_cache()
    backend = stt.resolve_backend("faster")
    assert backend.name == "faster"
    assert isinstance(backend, stt.FasterWhisperBackend)


def test_resolve_caches_same_instance():
    _reset_cache()
    first = stt.resolve_backend("faster")
    second = stt.resolve_backend("faster")
    assert first is second  # model stays loaded between turns


def test_mlx_falls_back_to_faster_when_unavailable(monkeypatch):
    """On a machine without mlx-whisper (e.g. Windows), 'mlx' resolves to faster."""
    _reset_cache()
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mlx_whisper":
            raise ImportError("no mlx on this platform")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    backend = stt.resolve_backend("mlx")
    assert backend.name == "faster"


def test_transcribe_delegates_to_backend(monkeypatch):
    _reset_cache()
    captured = {}

    class FakeBackend:
        name = "faster"

        def transcribe(self, audio, model_name, *, hotwords=None):
            captured.update(model=model_name, hotwords=hotwords)
            return "hello world"

    monkeypatch.setattr(stt, "resolve_backend", lambda _b: FakeBackend())
    out = stt.transcribe([0.0, 0.1], "small", "faster", hotwords="Jack, Sarah")
    assert out == "hello world"
    assert captured == {"model": "small", "hotwords": "Jack, Sarah"}
