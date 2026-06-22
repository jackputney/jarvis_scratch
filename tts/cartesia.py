"""
tts/cartesia.py — Streaming TTS for Jarvis.

Primary path: Cartesia Sonic API (SSE). Audio chunks are buffered, sample-aligned,
and played through pyaudio in steady frame sizes so the output device never sees
misaligned int16 samples (which sound like loud static between words).

Fallback path: macOS `say` / pyttsx3 local TTS when CARTESIA_API_KEY is unset.

The speak() function is the single public interface used by pipeline.py.
It blocks until the utterance is fully played.
"""

from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from typing import Callable

logger = logging.getLogger("jarvis.tts")

# macOS British male voice — matches the Cartesia voice's character and, unlike
# pyttsx3's nsss driver, the `say` subprocess works reliably from any thread.
_MACOS_SAY_VOICE = "Daniel"

try:
    import pyaudio
    _pa = pyaudio.PyAudio()
    PA_FORMAT = pyaudio.paInt16
except ImportError:
    pyaudio = None  # type: ignore[assignment]
    _pa = None
    PA_FORMAT = 8  # literal fallback when pyaudio is absent

# Cartesia returns raw PCM s16le mono.
SAMPLE_RATE = 44100
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes per sample
FRAME_BYTES = SAMPLE_WIDTH * CHANNELS  # one mono sample = 2 bytes

# PyAudio write size (must be a multiple of FRAME_BYTES). 2048 frames ≈ 46 ms.
WRITE_FRAMES = 2048
WRITE_BYTES = WRITE_FRAMES * FRAME_BYTES

# Hold ~120 ms of audio before the first write so the output buffer never underruns.
PREBUFFER_BYTES = int(SAMPLE_RATE * SAMPLE_WIDTH * 0.12)
DEFAULT_TRAILING_SILENCE_MS = 150

# Set by stop_speech(); checked during playback so the user can interrupt mid-utterance.
_cancel = threading.Event()
_local_proc: subprocess.Popen[bytes] | None = None
_local_lock = threading.Lock()


def _have_audio_output() -> bool:
    """True if any PCM output backend is available (sounddevice or PyAudio)."""
    try:
        import sounddevice  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return _pa is not None


class _OutputStream:
    """PCM s16le mono output via sounddevice (preferred) or PyAudio.

    sounddevice ships a bundled PortAudio binary (no build step), so the premium
    Cartesia voice keeps working — and stays interruptible — even when PyAudio
    isn't installed (e.g. Windows on Python 3.14). abort() drops buffered audio
    immediately so a barge-in / Stop cuts the reply with minimal tail.
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._sd = None
        self._pa_stream = None
        try:
            import sounddevice as sd

            self._sd = sd.RawOutputStream(
                samplerate=sample_rate, channels=CHANNELS, dtype="int16",
                blocksize=WRITE_FRAMES,
            )
            self._sd.start()
        except Exception:  # noqa: BLE001 — fall back to PyAudio if sounddevice fails
            self._sd = None
            if _pa is None:
                raise RuntimeError("no audio output backend (install sounddevice or pyaudio)")
            self._pa_stream = _pa.open(
                format=PA_FORMAT, channels=CHANNELS, rate=sample_rate,
                output=True, frames_per_buffer=WRITE_FRAMES,
            )
            self._pa_stream.start_stream()

    def write(self, frame: bytes) -> None:
        if self._sd is not None:
            self._sd.write(frame)
        else:
            self._pa_stream.write(frame)

    def close(self, abort: bool = False) -> None:
        if self._sd is not None:
            try:
                self._sd.abort() if abort else self._sd.stop()
            finally:
                self._sd.close()
        elif self._pa_stream is not None:
            try:
                self._pa_stream.stop_stream()
            finally:
                self._pa_stream.close()


# ---------------------------------------------------------------------------
# PCM playback helpers
# ---------------------------------------------------------------------------

def iter_aligned_writes(chunks: Iterator[bytes], write_bytes: int = WRITE_BYTES) -> Iterator[bytes]:
    """Re-chunk arbitrary byte blobs into sample-aligned PCM writes.

    HTTP/SSE chunks can split mid-sample (odd byte counts). Writing those directly
    to PyAudio shifts every subsequent sample and produces crackling/static,
    especially audible between words when new network chunks arrive.
    """
    if write_bytes % FRAME_BYTES != 0:
        raise ValueError("write_bytes must be a multiple of FRAME_BYTES")

    buffer = bytearray()
    for chunk in chunks:
        if not chunk:
            continue
        buffer.extend(chunk)
        while len(buffer) >= write_bytes:
            yield bytes(buffer[:write_bytes])
            del buffer[:write_bytes]

    tail = len(buffer) - (len(buffer) % FRAME_BYTES)
    if tail:
        yield bytes(buffer[:tail])


def _trailing_silence_ms() -> int:
    try:
        from config import Config

        return max(0, min(500, int(Config.load().tts_trailing_silence_ms)))
    except Exception:  # noqa: BLE001
        return DEFAULT_TRAILING_SILENCE_MS


def _silence_pcm(ms: int | None = None) -> bytes:
    duration = DEFAULT_TRAILING_SILENCE_MS if ms is None else max(0, ms)
    nbytes = int(SAMPLE_RATE * SAMPLE_WIDTH * duration / 1000)
    nbytes -= nbytes % FRAME_BYTES
    return b"\x00" * nbytes


def stop_speech() -> None:
    """Immediately halt any in-progress TTS (Cartesia stream or local say/pyttsx3)."""
    _cancel.set()
    with _local_lock:
        proc = _local_proc
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _play_pcm_stream(
    chunks: Iterator[bytes],
    on_first_chunk: Callable[[], None] | None = None,
    *,
    sample_rate: int = SAMPLE_RATE,
) -> None:
    """Play a stream of s16le mono PCM at sample_rate (sounddevice or PyAudio)."""
    audio_q: queue.Queue[bytes | None | Exception] = queue.Queue(maxsize=64)
    prebuffer_bytes = int(sample_rate * SAMPLE_WIDTH * 0.12)

    def _producer() -> None:
        try:
            for chunk in chunks:
                if _cancel.is_set():
                    break
                audio_q.put(chunk)
        except Exception as exc:  # noqa: BLE001
            audio_q.put(exc)
        finally:
            audio_q.put(None)

    threading.Thread(target=_producer, daemon=True, name="jarvis-tts-producer").start()

    stream = _OutputStream(sample_rate=sample_rate)

    def _incoming() -> Iterator[bytes]:
        while True:
            if _cancel.is_set():
                return
            item = audio_q.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    buffer = bytearray()
    first_audio = True
    playback_started = False

    try:
        for chunk in _incoming():
            if _cancel.is_set():
                break
            buffer.extend(chunk)

            if not playback_started and len(buffer) >= prebuffer_bytes:
                playback_started = True

            if not playback_started:
                continue

            while len(buffer) >= WRITE_BYTES:
                if _cancel.is_set():
                    break
                frame = bytes(buffer[:WRITE_BYTES])
                del buffer[:WRITE_BYTES]
                if first_audio:
                    first_audio = False
                    if on_first_chunk:
                        on_first_chunk()
                stream.write(frame)

        if not _cancel.is_set():
            tail = len(buffer) - (len(buffer) % FRAME_BYTES)
            if tail:
                if first_audio and on_first_chunk:
                    on_first_chunk()
                stream.write(bytes(buffer[:tail]))
    finally:
        stream.close(abort=_cancel.is_set())


# ---------------------------------------------------------------------------
# Fallback: pyttsx3 / macOS say
# ---------------------------------------------------------------------------

def _speak_local(text: str) -> None:
    """Speak text offline, blocking until playback finishes (or stop_speech())."""
    global _local_proc
    if sys.platform == "darwin" and shutil.which("say"):
        try:
            with _local_lock:
                _local_proc = subprocess.Popen(
                    ["say", "-v", _MACOS_SAY_VOICE, "-r", "175", text],
                )
            while True:
                with _local_lock:
                    proc = _local_proc
                if proc is None:
                    return
                if proc.poll() is not None:
                    return
                if _cancel.is_set():
                    proc.terminate()
                    return
                proc.wait(timeout=0.1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("⚠️  macOS 'say' failed (%s) — trying pyttsx3", exc)
        finally:
            with _local_lock:
                _local_proc = None
        return

    if _cancel.is_set():
        return
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        engine.say(text)
        engine.runAndWait()
    except Exception as exc:  # noqa: BLE001
        logger.error("❌  Local TTS failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Primary: Cartesia SSE streaming
# ---------------------------------------------------------------------------

def _iter_cartesia_audio(text: str, voice_id: str, api_key: str) -> Iterator[bytes]:
    """Yield PCM bytes from Cartesia's SSE endpoint (official SDK)."""
    from cartesia import Cartesia

    client = Cartesia(api_key=api_key)
    events = client.tts.generate_sse(
        model_id="sonic-2",
        transcript=text,
        voice={"mode": "id", "id": voice_id},
        output_format={
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": SAMPLE_RATE,
        },
    )
    for event in events:
        if getattr(event, "type", None) == "chunk":
            audio = getattr(event, "audio", None)
            if audio:
                yield audio
    if not _cancel.is_set():
        yield _silence_pcm(_trailing_silence_ms())


def _iter_cartesia_stream(
    text_chunks: Iterator[str], voice_id: str, api_key: str
) -> Iterator[bytes]:
    """Yield PCM bytes for a stream of text chunks (sentences) in order."""
    from cartesia import Cartesia

    client = Cartesia(api_key=api_key)
    for chunk in text_chunks:
        if _cancel.is_set():
            return
        text = chunk.strip()
        if not text:
            continue
        events = client.tts.generate_sse(
            model_id="sonic-2",
            transcript=text,
            voice={"mode": "id", "id": voice_id},
            output_format={
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": SAMPLE_RATE,
            },
        )
        for event in events:
            if _cancel.is_set():
                return
            if getattr(event, "type", None) == "chunk":
                audio = getattr(event, "audio", None)
                if audio:
                    yield audio
        if not _cancel.is_set():
            yield _silence_pcm(_trailing_silence_ms())


def _speak_cartesia(
    text: str,
    voice_id: str,
    on_first_chunk: Callable[[], None] | None = None,
) -> None:
    """Stream TTS audio from Cartesia Sonic and play via pyaudio."""
    api_key = os.environ.get("CARTESIA_API_KEY", "")
    if not api_key:
        _speak_local(text)
        return

    if not _have_audio_output():
        _speak_local(text)
        return

    try:
        _play_pcm_stream(_iter_cartesia_audio(text, voice_id, api_key), on_first_chunk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("⚠️  Cartesia TTS error (%s) — falling back to local TTS", exc)
        _speak_local(text)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def speak_cartesia(
    text: str,
    voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091",
    on_first_chunk: Callable[[], None] | None = None,
) -> None:
    """Speak text via Cartesia (or local fallback when key missing)."""
    if not text or not text.strip():
        return

    _cancel.clear()

    api_key = os.environ.get("CARTESIA_API_KEY", "")
    if api_key:
        _speak_cartesia(text, voice_id, on_first_chunk)
    else:
        _speak_local(text)


def speak_cartesia_stream(
    text_chunks: Iterator[str],
    voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091",
    on_first_chunk: Callable[[], None] | None = None,
) -> None:
    """Speak streaming sentence chunks via Cartesia."""
    _cancel.clear()
    api_key = os.environ.get("CARTESIA_API_KEY", "")

    if not api_key:
        for chunk in text_chunks:
            if _cancel.is_set():
                return
            text = chunk.strip()
            if not text:
                continue
            if on_first_chunk is not None:
                on_first_chunk()
                on_first_chunk = None
            _speak_local(text)
        return

    try:
        _play_pcm_stream(_iter_cartesia_stream(text_chunks, voice_id, api_key), on_first_chunk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("⚠️  Cartesia TTS error (%s) — falling back to local TTS", exc)
        for chunk in text_chunks:
            if _cancel.is_set():
                return
            if chunk and chunk.strip():
                _speak_local(chunk.strip())


def speak(
    text: str,
    voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091",
    on_first_chunk: Callable[[], None] | None = None,
) -> None:
    """Speak text aloud via the configured TTS router."""
    from tts.router import speak as route_speak

    route_speak(text, voice_id=voice_id, on_first_chunk=on_first_chunk)


def speak_stream(
    text_chunks: Iterator[str],
    voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091",
    on_first_chunk: Callable[[], None] | None = None,
) -> None:
    """Speak a stream of text chunks via the configured TTS router."""
    from tts.router import speak_stream as route_speak_stream

    route_speak_stream(text_chunks, voice_id=voice_id, on_first_chunk=on_first_chunk)
