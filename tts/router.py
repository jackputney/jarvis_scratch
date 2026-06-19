"""tts/router.py — dispatch TTS to ElevenLabs, Cartesia, or local pyttsx3."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any

from config import Config
from tts import cartesia, elevenlabs
from tts.errors import TTSError

logger = logging.getLogger("jarvis.tts")


def _cfg() -> Config:
    return Config.load()


def _resolve_cartesia_voice(voice_id: str | None, cfg: Config) -> str:
    return voice_id or cfg.cartesia_voice_id


def _resolve_elevenlabs_voice(voice_id: str | None, cfg: Config) -> str:
    return voice_id or cfg.elevenlabs_voice_id


def stop_speech() -> None:
    elevenlabs.stop()


def speak(
    text: str,
    voice_id: str | None = None,
    on_first_chunk: Callable[[], None] | None = None,
    *,
    provider: str | None = None,
) -> None:
    """Speak text using the configured TTS provider with automatic fallback."""
    if not (text or "").strip():
        return

    cfg = _cfg()
    chosen = (provider or cfg.tts_provider or "elevenlabs").strip().lower()

    if chosen == "pyttsx3":
        logger.debug("🔊 TTS provider: pyttsx3 (local)")
        cartesia._speak_local(text)
        return

    if chosen == "cartesia":
        logger.debug("🔊 TTS provider: Cartesia")
        cartesia.speak_cartesia(
            text,
            _resolve_cartesia_voice(voice_id, cfg),
            on_first_chunk=on_first_chunk,
        )
        return

    logger.debug("🔊 TTS provider: ElevenLabs")
    try:
        elevenlabs.speak(
            text,
            voice_id=_resolve_elevenlabs_voice(voice_id, cfg),
            model_id=cfg.elevenlabs_model_id,
            on_first_chunk=on_first_chunk,
        )
    except TTSError as exc:
        logger.debug("ElevenLabs unavailable (%s) — falling back to Cartesia", exc)
        cartesia.speak_cartesia(
            text,
            _resolve_cartesia_voice(None, cfg),
            on_first_chunk=on_first_chunk,
        )


def speak_stream(
    text_chunks: Iterator[str],
    voice_id: str | None = None,
    on_first_chunk: Callable[[], None] | None = None,
    *,
    provider: str | None = None,
) -> None:
    """Speak streaming sentence chunks using the configured provider."""
    cfg = _cfg()
    chosen = (provider or cfg.tts_provider or "elevenlabs").strip().lower()

    if chosen == "pyttsx3":
        logger.debug("🔊 TTS stream provider: pyttsx3 (local)")
        for chunk in text_chunks:
            text = (chunk or "").strip()
            if text:
                if on_first_chunk is not None:
                    on_first_chunk()
                    on_first_chunk = None
                cartesia._speak_local(text)
        return

    if chosen == "cartesia":
        logger.debug("🔊 TTS stream provider: Cartesia")
        cartesia.speak_cartesia_stream(
            text_chunks,
            _resolve_cartesia_voice(voice_id, cfg),
            on_first_chunk=on_first_chunk,
        )
        return

    logger.debug("🔊 TTS stream provider: ElevenLabs")
    try:
        elevenlabs.speak_stream(
            text_chunks,
            voice_id=_resolve_elevenlabs_voice(voice_id, cfg),
            model_id=cfg.elevenlabs_model_id,
            on_first_chunk=on_first_chunk,
        )
    except TTSError as exc:
        logger.debug("ElevenLabs stream unavailable (%s) — falling back to Cartesia", exc)
        cartesia.speak_cartesia_stream(
            text_chunks,
            _resolve_cartesia_voice(None, cfg),
            on_first_chunk=on_first_chunk,
        )


def speak_preview(
    text: str,
    voice_id: str,
    *,
    provider: str | None = None,
) -> None:
    """Speak a short preview clip (dashboard voice picker)."""
    speak(text, voice_id=voice_id, provider=provider or "elevenlabs")
