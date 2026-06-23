"""Speech-to-text backend adapter.

Picks the right STT engine for the platform and owns its model lifecycle:

  - ``mlx-whisper``    — Apple Silicon (Metal-accelerated), macOS only
  - ``faster-whisper`` — Windows / Linux / any CPU (the cross-platform default)

Core code (``pipeline._transcribe`` / ``pipeline.warmup_stt``) calls
``transcribe()`` / ``warmup()`` and never imports a specific engine. If the
configured backend is unavailable (e.g. ``mlx`` requested on Windows), it falls
back to ``faster-whisper`` automatically.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger("jarvis.adapters.stt")


class STTBackend(Protocol):
    """Minimal contract every speech-to-text engine implements."""

    name: str

    def warmup(self, model_name: str) -> None: ...

    def transcribe(self, audio: Any, model_name: str, *, hotwords: str | None = None) -> str: ...


class FasterWhisperBackend:
    """faster-whisper (CTranslate2) — the cross-platform CPU default."""

    name = "faster"

    def __init__(self) -> None:
        self._model: Any = None
        self._model_name: str | None = None

    def _ensure(self, model_name: str) -> Any:
        from faster_whisper import WhisperModel

        if self._model is None or self._model_name != model_name:
            self._model = WhisperModel(model_name, compute_type="int8")
            self._model_name = model_name
        return self._model

    def warmup(self, model_name: str) -> None:
        if self._model is None or self._model_name != model_name:
            logger.info("🎧 Warming faster-whisper model %r…", model_name)
        self._ensure(model_name)

    def transcribe(self, audio: Any, model_name: str, *, hotwords: str | None = None) -> str:
        model = self._ensure(model_name)
        segments, _info = model.transcribe(
            audio,
            beam_size=3,
            language="en",
            vad_filter=True,
            hotwords=hotwords,
        )
        return " ".join(s.text for s in segments).strip()


class MlxWhisperBackend:
    """mlx-whisper — Apple Silicon. Loads the model lazily on first transcription."""

    name = "mlx"

    def warmup(self, model_name: str) -> None:
        logger.info("🎧 STT backend mlx — model loads on first transcription.")

    def transcribe(self, audio: Any, model_name: str, *, hotwords: str | None = None) -> str:
        import mlx_whisper  # type: ignore[import]

        repo = f"mlx-community/whisper-{model_name}-mlx"
        result = mlx_whisper.transcribe(audio, path_or_hf_repo=repo)
        return (result.get("text", "") or "").strip()


# Cached backend instance (holds the loaded model between turns).
_backend: STTBackend | None = None


def resolve_backend(stt_backend: str) -> STTBackend:
    """Return the STT backend to use, falling back to faster-whisper when mlx is absent."""
    global _backend
    want = (stt_backend or "mlx").strip().lower()

    if want != "faster":
        try:
            import mlx_whisper  # type: ignore[import]  # noqa: F401
        except ImportError:
            logger.warning("⚠️  mlx-whisper unavailable — using faster-whisper for STT.")
            want = "faster"

    if _backend is None or _backend.name != want:
        _backend = MlxWhisperBackend() if want == "mlx" else FasterWhisperBackend()
    return _backend


def transcribe(audio: Any, model_name: str, stt_backend: str, *, hotwords: str | None = None) -> str:
    """Transcribe a float32 mono waveform with the resolved backend."""
    return resolve_backend(stt_backend).transcribe(audio, model_name, hotwords=hotwords)


def warmup(model_name: str, stt_backend: str) -> None:
    """Pre-load the STT model for the resolved backend (skips Google/STT cold start)."""
    resolve_backend(stt_backend).warmup(model_name)
