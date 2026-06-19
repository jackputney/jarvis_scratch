"""tts/router.py — dispatch TTS to ElevenLabs, Cartesia, or local pyttsx3."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator

from config import Config
from tts import cartesia, elevenlabs
from tts.errors import TTSError

logger = logging.getLogger("jarvis.tts")


def _cfg() -> Config:
    """Always re-read config.json so dashboard voice/provider changes apply live."""
    return Config.load_fresh()


def _resolve_cartesia_voice(voice_id: str | None, cfg: Config) -> str:
    return voice_id or cfg.cartesia_voice_id


def _resolve_elevenlabs_voice(voice_id: str | None, cfg: Config) -> str:
    return voice_id or cfg.elevenlabs_voice_id


def _chosen_provider(cfg: Config, provider: str | None) -> str:
    chosen = (provider or cfg.tts_provider or "elevenlabs").strip().lower()
    if chosen == "elevenlabs" and not (cfg.elevenlabs_api_key or "").strip():
        if (cfg.cartesia_api_key or "").strip():
            return "cartesia"
        return "pyttsx3"
    if chosen == "cartesia" and not (cfg.cartesia_api_key or "").strip():
        if (cfg.elevenlabs_api_key or "").strip():
            return "elevenlabs"
        return "pyttsx3"
    return chosen


def stop_speech() -> None:
    elevenlabs.stop()


def _speak_with_cfg(
    text: str,
    cfg: Config,
    voice_id: str | None,
    on_first_chunk: Callable[[], None] | None,
    provider: str | None,
) -> None:
    chosen = _chosen_provider(cfg, provider)

    if chosen == "pyttsx3":
        logger.debug("🔊 TTS provider: pyttsx3 (local)")
        cartesia._speak_local(text)
        return

    if chosen == "cartesia":
        logger.debug("🔊 TTS provider: Cartesia (voice=%s)", _resolve_cartesia_voice(voice_id, cfg))
        cartesia.speak_cartesia(
            text,
            _resolve_cartesia_voice(voice_id, cfg),
            on_first_chunk=on_first_chunk,
        )
        return

    resolved_voice = _resolve_elevenlabs_voice(voice_id, cfg)
    logger.debug(
        "🔊 TTS provider: ElevenLabs (voice=%s, model=%s)",
        resolved_voice,
        cfg.elevenlabs_model_id,
    )
    try:
        elevenlabs.speak(
            text,
            voice_id=resolved_voice,
            model_id=cfg.elevenlabs_model_id,
            on_first_chunk=on_first_chunk,
        )
    except TTSError as exc:
        logger.warning("⚠️  ElevenLabs unavailable (%s) — falling back to Cartesia", exc)
        cartesia.speak_cartesia(
            text,
            _resolve_cartesia_voice(None, cfg),
            on_first_chunk=on_first_chunk,
        )


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
    from tts.cartesia import _cancel

    _cancel.clear()
    _speak_with_cfg(text.strip(), _cfg(), voice_id, on_first_chunk, provider)


def speak_stream(
    text_chunks: Iterator[str],
    voice_id: str | None = None,
    on_first_chunk: Callable[[], None] | None = None,
    *,
    provider: str | None = None,
) -> None:
    """Speak streaming sentence chunks; reloads provider/voice from config per chunk."""
    from tts.cartesia import _cancel

    _cancel.clear()
    first = True
    for chunk in text_chunks:
        if _cancelled():
            return
        text = (chunk or "").strip()
        if not text:
            continue
        cb = on_first_chunk if first else None
        first = False
        _speak_with_cfg(text, _cfg(), voice_id, cb, provider)


def _cancelled() -> bool:
    try:
        from tts.cartesia import _cancel

        return _cancel.is_set()
    except Exception:  # noqa: BLE001
        return False


def speak_preview(
    text: str,
    voice_id: str,
    *,
    provider: str | None = None,
) -> None:
    """Speak a short preview clip (dashboard voice picker)."""
    speak(text, voice_id=voice_id, provider=provider or "elevenlabs")
