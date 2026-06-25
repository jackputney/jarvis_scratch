"""Microphone capture adapter.

Owns frame constants, VAD helpers, the mic listener thread (sounddevice with
PyAudio fallback), and utterance capture from the shared capture queue.

``pipeline.py`` calls these helpers and never opens audio hardware directly.
See ``docs/PLATFORM.md`` for the adapter-layer design.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import events
from config import Config
from tts.cartesia import stop_speech
from voice.speech_state import BargeInGate, SpeechPhase

logger = logging.getLogger("jarvis.adapters.audio_io")


def _log_wake(word: str, confidence: float, accepted: bool) -> None:
    try:
        from adapters.wake_metrics import log_wake_event
        log_wake_event(word, confidence, accepted)
    except Exception:  # noqa: BLE001
        pass

try:
    import pyaudio
except ImportError:
    pyaudio = None  # type: ignore[assignment]

try:
    import webrtcvad
except ImportError:
    webrtcvad = None  # type: ignore[assignment,misc]

# --- Frame / capture constants ------------------------------------------------

AUDIO_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(AUDIO_RATE * FRAME_DURATION_MS / 1000)
CHANNELS = 1
PA_FORMAT = pyaudio.paInt16 if pyaudio is not None else None
SAMPLE_WIDTH = 2
ENERGY_VAD_THRESHOLD = 250
MAX_RECORD_SECONDS = 30
PRE_ROLL_FRAMES = 8
WAKE_CONSECUTIVE_HITS = 2
AUDIO_THREAD_RESTART_DELAY = 2.0
QUEUE_POLL_SEC = 0.05


# --- VAD helpers --------------------------------------------------------------


def barge_energy_threshold(cfg: Config) -> int:
    """Scale energy VAD threshold from config barge_in_threshold (0.5 = baseline)."""
    return max(500, int(ENERGY_VAD_THRESHOLD * 2 * cfg.barge_in_threshold / 0.5))


def frame_is_speech(
    data: bytes,
    cfg: Config,
    *,
    energy_threshold: int | None = None,
) -> bool:
    """True when a single mic frame looks like user speech (webrtcvad or RMS)."""
    if webrtcvad is not None:
        try:
            result = webrtcvad.Vad(2).is_speech(data, AUDIO_RATE)
            if isinstance(result, bool):
                return result
        except Exception:  # noqa: BLE001
            pass
    import numpy as np

    audio = np.frombuffer(data, dtype=np.int16)
    if audio.size == 0:
        return False
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    threshold = energy_threshold if energy_threshold is not None else ENERGY_VAD_THRESHOLD
    return rms > threshold


def is_speech_energy(data: bytes) -> bool:
    """Lightweight energy-based speech detector — fallback when webrtcvad is absent."""
    return frame_is_speech(data, Config.load())


def read_audio_frame(stream: Any, *, use_sounddevice: bool) -> bytes:
    if use_sounddevice:
        data, _overflowed = stream.read(FRAME_SIZE)
        import numpy as np

        return np.asarray(data, dtype=np.int16).reshape(-1).tobytes()
    return stream.read(FRAME_SIZE, exception_on_overflow=False)


# --- Mic listener -------------------------------------------------------------


def _reset_oww(model: Any) -> None:
    try:
        for buf in model.prediction_buffer.values():
            buf.clear()
    except Exception:  # noqa: BLE001
        pass


def _wake_detection_paused(
    capturing: threading.Event,
    paused: threading.Event,
    *,
    pipeline_state: str | None = None,
) -> bool:
    """Lazy import avoids a circular dependency with pipeline at module load."""
    from pipeline import wake_detection_paused

    return wake_detection_paused(capturing, paused, pipeline_state=pipeline_state)


def audio_loop(
    wake_event: threading.Event,
    capture_queue: queue.Queue[bytes],
    capturing: threading.Event,
    paused: threading.Event,
    audio_stop: threading.Event,
    wake_word: str,
    barge_gate: BargeInGate,
) -> None:
    import numpy as np
    from openwakeword.model import Model

    oww_model = Model(wakeword_models=[wake_word], inference_framework="onnx")
    use_sounddevice = False
    sd_stream = None
    pa = None
    pa_stream = None

    try:
        import sounddevice as sd

        sd_stream = sd.InputStream(
            samplerate=AUDIO_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=FRAME_SIZE,
        )
        sd_stream.start()
        use_sounddevice = True
        logger.info("🎤 Audio input: sounddevice")
    except Exception as exc:  # noqa: BLE001
        if pyaudio is None:
            raise RuntimeError(
                "No audio backend available: sounddevice failed to open and PyAudio "
                "isn't installed."
            ) from exc
        logger.info("🎤 Audio input: PyAudio (sounddevice unavailable: %s)", exc)
        pa = pyaudio.PyAudio()
        pa_stream = pa.open(
            rate=AUDIO_RATE,
            channels=CHANNELS,
            format=PA_FORMAT,
            input=True,
            frames_per_buffer=FRAME_SIZE,
        )

    stream = sd_stream if use_sounddevice else pa_stream
    logger.info("👂 Wake word listener active — say '%s' to activate", wake_word)

    was_inactive = False
    audio_cfg = Config.load()
    audio_cfg_ts = time.monotonic()
    try:
        while not audio_stop.is_set():
            data = read_audio_frame(stream, use_sounddevice=use_sounddevice)

            if capturing.is_set():
                capture_queue.put(data)
                was_inactive = True
                continue

            pipeline_state = events.get_state().get("pipeline_state", "IDLE")
            now = time.monotonic()
            if now - audio_cfg_ts >= 2.0:
                audio_cfg = Config.load()
                audio_cfg_ts = now
            cfg = audio_cfg

            if (
                pipeline_state == SpeechPhase.SPEAKING.value
                and barge_gate.armed.is_set()
                and cfg.barge_in_enabled
            ):
                barge_energy = barge_energy_threshold(cfg)
                required = max(2, int(cfg.barge_in_min_ms / FRAME_DURATION_MS))
                if frame_is_speech(data, cfg, energy_threshold=barge_energy):
                    barge_gate.speech_frames += 1
                    capture_queue.put(data)
                    if barge_gate.speech_frames >= required:
                        logger.info("🎙️  VAD barge-in — stopping reply to listen.")
                        stop_speech()
                        barge_gate.triggered.set()
                        barge_gate.armed.clear()
                        capturing.set()
                        was_inactive = True
                else:
                    barge_gate.speech_frames = 0
                continue

            if _wake_detection_paused(capturing, paused, pipeline_state=pipeline_state):
                was_inactive = True
                continue

            if was_inactive:
                _reset_oww(oww_model)
                was_inactive = False

            audio_int16 = np.frombuffer(data, dtype=np.int16)
            oww_model.predict(audio_int16)
            threshold = audio_cfg.wakeword_threshold
            hits = WAKE_CONSECUTIVE_HITS
            for name, scores in oww_model.prediction_buffer.items():
                if len(scores) < hits:
                    continue
                score = scores[-1]
                accepted = all(scores[-i] > threshold for i in range(1, hits + 1))
                if accepted:
                    logger.info(
                        "🎙️  Wake word '%s' detected (score=%.2f)",
                        name, score,
                    )
                    _log_wake(name, score, True)
                    _reset_oww(oww_model)
                    capture_queue.put(data)
                    capturing.set()
                    wake_event.set()
                    break
                elif score > threshold * 0.5:
                    _log_wake(name, score, False)
    finally:
        if use_sounddevice and sd_stream is not None:
            sd_stream.stop()
            sd_stream.close()
        elif pa_stream is not None:
            pa_stream.stop_stream()
            pa_stream.close()
        if pa is not None:
            pa.terminate()


class AudioIOBackend(Protocol):
    """Contract for mic capture backends."""

    def start(
        self,
        wake_event: threading.Event,
        capture_queue: queue.Queue[bytes],
        capturing: threading.Event,
        paused: threading.Event,
        audio_stop: threading.Event,
        wake_word: str,
        barge_gate: BargeInGate,
    ) -> threading.Thread: ...

    def stop(self, audio_stop: threading.Event) -> None: ...


class _MicCaptureBackend:
    """sounddevice-first mic capture with PyAudio fallback inside ``audio_loop``."""

    name = "mic"

    def start(
        self,
        wake_event: threading.Event,
        capture_queue: queue.Queue[bytes],
        capturing: threading.Event,
        paused: threading.Event,
        audio_stop: threading.Event,
        wake_word: str,
        barge_gate: BargeInGate,
    ) -> threading.Thread:
        return start_audio_thread(
            wake_event,
            capture_queue,
            capturing,
            paused,
            audio_stop,
            wake_word,
            barge_gate,
        )

    def stop(self, audio_stop: threading.Event) -> None:
        audio_stop.set()


_backend: AudioIOBackend | None = None


def resolve_backend() -> AudioIOBackend:
    """Return the mic capture backend (currently a single cross-platform implementation)."""
    global _backend
    if _backend is None:
        _backend = _MicCaptureBackend()
    return _backend


def start_audio_thread(
    wake_event: threading.Event,
    capture_queue: queue.Queue[bytes],
    capturing: threading.Event,
    paused: threading.Event,
    audio_stop: threading.Event,
    wake_word: str,
    barge_gate: BargeInGate,
) -> threading.Thread:
    def _run() -> None:
        try:
            import openwakeword.model  # noqa: F401
        except ImportError:
            logger.warning("⚠️  openwakeword not installed — wake word disabled.")
            while not audio_stop.is_set():
                try:
                    input()
                    if not (capturing.is_set() or paused.is_set()):
                        wake_event.set()
                except EOFError:
                    time.sleep(3600)
            return

        while not audio_stop.is_set():
            try:
                audio_loop(
                    wake_event,
                    capture_queue,
                    capturing,
                    paused,
                    audio_stop,
                    wake_word,
                    barge_gate,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "⚠️  Audio listener crashed (%s) — restarting in %.0fs",
                    exc, AUDIO_THREAD_RESTART_DELAY, exc_info=True,
                )
                time.sleep(AUDIO_THREAD_RESTART_DELAY)
            else:
                if not audio_stop.is_set():
                    logger.warning(
                        "⚠️  Audio listener exited unexpectedly — restarting in %.0fs",
                        AUDIO_THREAD_RESTART_DELAY,
                    )
                    time.sleep(AUDIO_THREAD_RESTART_DELAY)

    t = threading.Thread(target=_run, daemon=True, name="jarvis-audio")
    t.start()
    return t


# --- Utterance capture --------------------------------------------------------


def record_from_queue(
    capture_queue: queue.Queue[bytes],
    wait_for_speech_frames: int,
    *,
    silence_ms: int = 1400,
    min_capture_ms: int = 2500,
    interrupt_check: Callable[[], bool] | None = None,
) -> bytes:
    """Drain the capture queue until trailing silence ends the utterance."""

    def _interrupted() -> bool:
        if interrupt_check is not None:
            return interrupt_check()
        from pipeline import interrupt_requested

        return interrupt_requested()

    vad = webrtcvad.Vad(2) if webrtcvad else None
    frames: list[bytes] = []
    silent_frames = 0
    speech_started = False
    max_frames = int(MAX_RECORD_SECONDS * 1000 / FRAME_DURATION_MS)
    post_speech_silence_frames = max(10, int(silence_ms / FRAME_DURATION_MS))
    min_capture_frames = max(15, int(min_capture_ms / FRAME_DURATION_MS))

    logger.info("🎙️  Listening…")
    for i in range(max_frames):
        if _interrupted():
            logger.info("⏹️  Stop during listening.")
            return b""

        try:
            data = capture_queue.get(timeout=QUEUE_POLL_SEC)
        except queue.Empty:
            if speech_started:
                continue
            if i >= wait_for_speech_frames:
                logger.debug("🎙️  Capture timed out waiting for speech.")
                break
            continue

        is_speech = vad.is_speech(data, AUDIO_RATE) if vad else is_speech_energy(data)
        if is_speech:
            speech_started = True
            silent_frames = 0
            frames.append(data)
        elif speech_started:
            silent_frames += 1
            frames.append(data)
            if i >= min_capture_frames and silent_frames > post_speech_silence_frames:
                logger.debug(
                    "🎙️  Ending capture after %.1fs (%.0fms trailing silence).",
                    (i + 1) * FRAME_DURATION_MS / 1000,
                    silent_frames * FRAME_DURATION_MS,
                )
                break
        else:
            frames.append(data)
            if len(frames) > PRE_ROLL_FRAMES:
                frames.pop(0)

    if not speech_started:
        return b""
    return b"".join(frames)
