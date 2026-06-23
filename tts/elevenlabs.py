"""tts/elevenlabs.py — ElevenLabs streaming TTS (primary provider)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator

from tts.cartesia import (
    _cancel,
    _play_pcm_stream,
    _silence_pcm,
    _trailing_silence_ms,
    stop_speech as cartesia_stop_speech,
)
from tts.errors import TTSError

logger = logging.getLogger("jarvis.tts.elevenlabs")

DEFAULT_MODEL = "eleven_flash_v2_5"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"
# pcm_44100 requires ElevenLabs Pro; pcm_22050 works on free/starter tiers (fuller than pcm_16000).
ELEVENLABS_SAMPLE_RATE = 22050
OUTPUT_FORMAT = "pcm_22050"


def _tts_error_from_exc(exc: Exception) -> TTSError:
    """Build a TTSError message that includes HTTP status when the SDK exposes it."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)
    body = str(exc).strip()
    if status is not None:
        msg = f"ElevenLabs API error {status}: {body}" if body else f"ElevenLabs API error {status}"
    else:
        msg = body or repr(exc)
    return TTSError(msg)


def _api_key() -> str:
    return (os.environ.get("ELEVENLABS_API_KEY") or "").strip()


def _silence_pcm_ms(ms: int, sample_rate: int = ELEVENLABS_SAMPLE_RATE) -> bytes:
    nbytes = int(sample_rate * 2 * max(0, ms) / 1000)
    if nbytes % 2:
        nbytes += 1
    return b"\x00" * nbytes


def _iter_elevenlabs_audio(
    text: str,
    voice_id: str,
    model_id: str,
    api_key: str,
) -> Iterator[bytes]:
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=api_key)
    stream = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=model_id,
        output_format=OUTPUT_FORMAT,
    )
    for chunk in stream:
        if _cancel.is_set():
            return
        if chunk:
            yield chunk
    if not _cancel.is_set():
        yield _silence_pcm(_trailing_silence_ms(), sample_rate=ELEVENLABS_SAMPLE_RATE)


def _iter_elevenlabs_stream(
    text_chunks: Iterator[str],
    voice_id: str,
    model_id: str,
    api_key: str,
) -> Iterator[bytes]:
    for chunk in text_chunks:
        if _cancel.is_set():
            return
        text = (chunk or "").strip()
        if not text:
            continue
        yield from _iter_elevenlabs_audio(text, voice_id, model_id, api_key)


def speak(
    text: str,
    voice_id: str = DEFAULT_VOICE,
    model_id: str = DEFAULT_MODEL,
    on_first_chunk: Callable[[], None] | None = None,
) -> None:
    """Stream ElevenLabs audio and play via sounddevice. Raises TTSError on failure."""
    if not (text or "").strip():
        return
    api_key = _api_key()
    if not api_key:
        raise TTSError("ELEVENLABS_API_KEY is not set")

    _cancel.clear()
    try:
        _play_pcm_stream(
            _iter_elevenlabs_audio(text.strip(), voice_id, model_id, api_key),
            on_first_chunk,
            sample_rate=ELEVENLABS_SAMPLE_RATE,
        )
    except TTSError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _tts_error_from_exc(exc) from exc


def speak_stream(
    text_chunks: Iterator[str],
    voice_id: str = DEFAULT_VOICE,
    model_id: str = DEFAULT_MODEL,
    on_first_chunk: Callable[[], None] | None = None,
) -> None:
    """Stream multiple text chunks through one ElevenLabs playback session."""
    api_key = _api_key()
    if not api_key:
        raise TTSError("ELEVENLABS_API_KEY is not set")

    _cancel.clear()
    try:
        _play_pcm_stream(
            _iter_elevenlabs_stream(text_chunks, voice_id, model_id, api_key),
            on_first_chunk,
            sample_rate=ELEVENLABS_SAMPLE_RATE,
        )
    except TTSError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _tts_error_from_exc(exc) from exc


def stop() -> None:
    """Halt in-progress ElevenLabs playback (shared with Cartesia/local)."""
    cartesia_stop_speech()
