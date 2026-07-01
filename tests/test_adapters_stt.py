"""STT adapter: backend resolution and fallback (no model loading)."""

from __future__ import annotations

import builtins

import adapters.stt as stt


def _reset_cache():
    stt._backend = None
    stt._resolved_faster_models.clear()


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

        def transcribe(self, audio, model_name, *, hotwords=None, device="", compute_type=""):
            captured.update(
                model=model_name,
                hotwords=hotwords,
                device=device,
                compute_type=compute_type,
            )
            return "hello world"

    monkeypatch.setattr(stt, "resolve_backend", lambda _b: FakeBackend())
    out = stt.transcribe(
        [0.0, 0.1],
        "large-v3-turbo",
        "faster",
        hotwords="Jack, Sarah",
        device="cuda",
        compute_type="float16",
    )
    assert out == "hello world"
    assert captured == {
        "model": "large-v3-turbo",
        "hotwords": "Jack, Sarah",
        "device": "cuda",
        "compute_type": "float16",
    }


def test_resolve_faster_whisper_model_prefers_native_turbo_tag():
    _reset_cache()
    assert stt.resolve_faster_whisper_model("large-v3-turbo") == "large-v3-turbo"


def test_mlx_repo_large_v3_turbo_omits_mlx_suffix():
    assert stt.mlx_repo("large-v3-turbo") == "mlx-community/whisper-large-v3-turbo"
    assert stt.mlx_repo("small") == "mlx-community/whisper-small-mlx"


def test_resolve_device_compute_auto():
    device, compute = stt.resolve_device_compute("", "")
    assert device in ("cuda", "cpu")
    assert compute == ("float16" if device == "cuda" else "int8")


def test_resolve_device_compute_config_override():
    device, compute = stt.resolve_device_compute("cpu", "int8")
    assert device == "cpu"
    assert compute == "int8"


def test_faster_ensure_passes_device_compute(monkeypatch):
    _reset_cache()
    calls = []

    class FakeWhisperModel:
        def __init__(self, model_name, *, device, compute_type):
            calls.append((model_name, device, compute_type))

        def transcribe(self, *args, **kwargs):
            return [], None

    monkeypatch.setattr(
        "faster_whisper.WhisperModel",
        FakeWhisperModel,
    )
    backend = stt.FasterWhisperBackend()
    backend._ensure("large-v3-turbo", device="cpu", compute_type="int8")
    assert calls == [("large-v3-turbo", "cpu", "int8")]

