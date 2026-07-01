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

# MLX repos do not all follow whisper-{model}-mlx (turbo omits the -mlx suffix).
_MLX_REPO_OVERRIDES: dict[str, str] = {
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}

# faster-whisper 1.1+ maps large-v3-turbo via Systran; CT2 repo is the offline fallback.
_FASTER_TURBO_CANDIDATES: tuple[str, ...] = (
    "large-v3-turbo",
    "turbo",
    "deepdml/faster-whisper-large-v3-turbo-ct2",
)
_FASTER_LARGE_V3_FALLBACK = "large-v3"

_resolved_faster_models: dict[str, str] = {}


def mlx_repo(model_name: str) -> str:
    """Map a config ``stt_model`` value to the mlx-community Hugging Face repo."""
    return _MLX_REPO_OVERRIDES.get(model_name, f"mlx-community/whisper-{model_name}-mlx")


def resolve_faster_whisper_model(model_name: str) -> str:
    """Resolve a config model name to a faster-whisper / CT2 repo id."""
    if model_name in _resolved_faster_models:
        return _resolved_faster_models[model_name]

    if model_name not in ("large-v3-turbo", "turbo"):
        _resolved_faster_models[model_name] = model_name
        return model_name

    resolved = _FASTER_TURBO_CANDIDATES[-1]
    try:
        from faster_whisper.utils import available_models

        avail = set(available_models())
        for candidate in _FASTER_TURBO_CANDIDATES:
            if candidate in avail:
                resolved = candidate
                break
    except Exception:  # noqa: BLE001
        pass

    _resolved_faster_models[model_name] = resolved
    return resolved


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def resolve_device_compute(device: str = "", compute_type: str = "") -> tuple[str, str]:
    """Pick device/compute_type from config overrides or hardware defaults."""
    want_device = (device or "").strip().lower()
    want_compute = (compute_type or "").strip().lower()

    if want_device and want_device not in ("auto", "default"):
        resolved_device = want_device
    else:
        resolved_device = "cuda" if _cuda_available() else "cpu"

    if want_compute and want_compute not in ("auto", "default"):
        resolved_compute = want_compute
    elif resolved_device == "cuda":
        resolved_compute = "float16"
    else:
        resolved_compute = "int8"

    return resolved_device, resolved_compute


class STTBackend(Protocol):
    """Minimal contract every speech-to-text engine implements."""

    name: str

    def warmup(
        self,
        model_name: str,
        *,
        device: str = "",
        compute_type: str = "",
    ) -> None: ...

    def transcribe(
        self,
        audio: Any,
        model_name: str,
        *,
        hotwords: str | None = None,
        device: str = "",
        compute_type: str = "",
    ) -> str: ...


class FasterWhisperBackend:
    """faster-whisper (CTranslate2) — cross-platform; CUDA float16 when available."""

    name = "faster"

    def __init__(self) -> None:
        self._model: Any = None
        self._model_name: str | None = None
        self._device: str | None = None
        self._compute_type: str | None = None

    def _load_model(self, model_name: str, device: str, compute_type: str) -> Any:
        from faster_whisper import WhisperModel

        resolved = resolve_faster_whisper_model(model_name)
        try:
            return WhisperModel(resolved, device=device, compute_type=compute_type)
        except Exception as exc:
            if resolved == _FASTER_LARGE_V3_FALLBACK or model_name not in ("large-v3-turbo", "turbo"):
                raise
            logger.warning(
                "⚠️  Could not load faster-whisper %r — falling back to %r: %s",
                resolved,
                _FASTER_LARGE_V3_FALLBACK,
                exc,
            )
            return WhisperModel(_FASTER_LARGE_V3_FALLBACK, device=device, compute_type=compute_type)

    def _ensure(self, model_name: str, *, device: str = "", compute_type: str = "") -> Any:
        resolved_device, resolved_compute = resolve_device_compute(device, compute_type)
        resolved_name = resolve_faster_whisper_model(model_name)
        if (
            self._model is None
            or self._model_name != resolved_name
            or self._device != resolved_device
            or self._compute_type != resolved_compute
        ):
            self._model = self._load_model(model_name, resolved_device, resolved_compute)
            self._model_name = resolved_name
            self._device = resolved_device
            self._compute_type = resolved_compute
        return self._model

    def warmup(self, model_name: str, *, device: str = "", compute_type: str = "") -> None:
        if self._model is None or self._model_name != resolve_faster_whisper_model(model_name):
            logger.info("🎧 Warming faster-whisper model %r…", model_name)
        self._ensure(model_name, device=device, compute_type=compute_type)

    def transcribe(
        self,
        audio: Any,
        model_name: str,
        *,
        hotwords: str | None = None,
        device: str = "",
        compute_type: str = "",
    ) -> str:
        model = self._ensure(model_name, device=device, compute_type=compute_type)
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

    def warmup(self, model_name: str, *, device: str = "", compute_type: str = "") -> None:
        logger.info("🎧 STT backend mlx — model loads on first transcription.")

    def transcribe(
        self,
        audio: Any,
        model_name: str,
        *,
        hotwords: str | None = None,
        device: str = "",
        compute_type: str = "",
    ) -> str:
        import mlx_whisper  # type: ignore[import]

        repo = mlx_repo(model_name)
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


def transcribe(
    audio: Any,
    model_name: str,
    stt_backend: str,
    *,
    hotwords: str | None = None,
    device: str = "",
    compute_type: str = "",
) -> str:
    """Transcribe a float32 mono waveform with the resolved backend."""
    return resolve_backend(stt_backend).transcribe(
        audio,
        model_name,
        hotwords=hotwords,
        device=device,
        compute_type=compute_type,
    )


def warmup(
    model_name: str,
    stt_backend: str,
    *,
    device: str = "",
    compute_type: str = "",
) -> None:
    """Pre-load the STT model for the resolved backend (skips Google/STT cold start)."""
    resolve_backend(stt_backend).warmup(model_name, device=device, compute_type=compute_type)
