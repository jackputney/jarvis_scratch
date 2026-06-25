"""tts/router.py — dispatch TTS to ElevenLabs, Cartesia, or local pyttsx3."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator

from config import Config
from tts import cartesia, elevenlabs
from tts.cartesia import _cancel
from tts.errors import TTSError

logger = logging.getLogger("jarvis.tts")


def _cfg() -> Config:
    """Always re-read config.json so dashboard voice/provider changes apply live."""
    return Config.load_fresh()


def _resolve_cartesia_voice(voice_id: str | None, cfg: Config) -> str:
    return voice_id or cfg.cartesia_voice_id


def _resolve_elevenlabs_voice(voice_id: str | None, cfg: Config) -> str:
    return voice_id or cfg.elevenlabs_voice_id


def effective_tts_provider(cfg: "Config", provider: str | None = None) -> str:
    """Provider that will actually run given configured API keys."""
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


def _chosen_provider(cfg: Config, provider: str | None) -> str:
    return effective_tts_provider(cfg, provider)


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "quota_exceeded" in msg or "quota exceeded" in msg or "credits remaining" in msg


def stop_speech() -> None:
    elevenlabs.stop()


def _record_tts(provider: str, ms: int, *, fallback: dict | None = None) -> None:
    from improvement.trace import get_active_trace, record_event

    active = get_active_trace()
    if active is None:
        return
    active.tts_ms = (active.tts_ms or 0) + ms
    active.details["tts_provider"] = provider
    if fallback:
        record_event(active.turn_id, "tts_fallback", fallback)


def _speak_with_cfg(
    text: str,
    cfg: Config,
    voice_id: str | None,
    on_first_chunk: Callable[[], None] | None,
    provider: str | None,
) -> None:
    chosen = _chosen_provider(cfg, provider)
    t0 = time.monotonic()

    if chosen == "pyttsx3":
        logger.error(
            "🔊 Using local Windows TTS (pyttsx3) — cloud voices unavailable. "
            "Check ElevenLabs/Cartesia credits or API keys."
        )
        logger.debug("🔊 TTS provider: pyttsx3 (local)")
        cartesia._speak_local(text)
        _record_tts("pyttsx3", int((time.monotonic() - t0) * 1000))
        return

    if chosen == "cartesia":
        logger.debug("🔊 TTS provider: Cartesia (voice=%s)", _resolve_cartesia_voice(voice_id, cfg))
        cartesia.speak_cartesia(
            text,
            _resolve_cartesia_voice(voice_id, cfg),
            on_first_chunk=on_first_chunk,
        )
        _record_tts("cartesia", int((time.monotonic() - t0) * 1000))
        return

    resolved_voice = _resolve_elevenlabs_voice(voice_id, cfg)
    logger.debug(
        "🔊 TTS provider: ElevenLabs (voice=%s, model=%s)",
        resolved_voice,
        cfg.elevenlabs_model_id,
    )
    last_exc: TTSError | None = None
    for attempt in range(3):
        if _cancel.is_set():
            return
        try:
            elevenlabs.speak(
                text,
                voice_id=resolved_voice,
                model_id=cfg.elevenlabs_model_id,
                on_first_chunk=on_first_chunk,
            )
            _record_tts("elevenlabs", int((time.monotonic() - t0) * 1000))
            return
        except TTSError as exc:
            last_exc = exc
            if _is_quota_error(exc):
                logger.error(
                    "ElevenLabs quota exceeded — no credits left. "
                    "Upgrade at elevenlabs.io or switch tts_provider in config.json."
                )
                break
            logger.warning("ElevenLabs attempt %d failed: %s", attempt + 1, exc)
            time.sleep(0.4 * (attempt + 1))
    logger.warning(
        "ElevenLabs unavailable (%s) — falling back to Cartesia",
        last_exc,
    )
    fb_t0 = time.monotonic()
    cartesia.speak_cartesia(
        text,
        _resolve_cartesia_voice(None, cfg),
        on_first_chunk=on_first_chunk,
    )
    _record_tts(
        "cartesia",
        int((time.monotonic() - fb_t0) * 1000),
        fallback={"from": "elevenlabs", "to": "cartesia", "reason": str(last_exc)[:200]},
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


def _buffering_chunk_iter(
    text_chunks: Iterator[str],
    buffer: list[str],
) -> Iterator[str]:
    """Pass chunks through while copying them for retry / fallback playback."""
    for chunk in text_chunks:
        if _cancelled():
            return
        text = (chunk or "").strip()
        if not text:
            continue
        buffer.append(text)
        yield text


def speak_stream(
    text_chunks: Iterator[str],
    voice_id: str | None = None,
    on_first_chunk: Callable[[], None] | None = None,
    *,
    provider: str | None = None,
) -> None:
    """Speak streaming sentence chunks in one continuous playback session."""
    from tts.cartesia import _cancel

    _cancel.clear()
    cfg = _cfg()
    chosen = _chosen_provider(cfg, provider)
    buffer: list[str] = []
    live = _buffering_chunk_iter(text_chunks, buffer)

    if chosen == "pyttsx3":
        for text in live:
            cartesia._speak_local(text)
        return

    if chosen == "cartesia":
        cartesia.speak_cartesia_stream(
            live,
            _resolve_cartesia_voice(voice_id, cfg),
            on_first_chunk=on_first_chunk,
        )
        return

    resolved_voice = _resolve_elevenlabs_voice(voice_id, cfg)
    last_exc: TTSError | None = None
    for attempt in range(3):
        if _cancel.is_set():
            return
        source: Iterator[str] = live if attempt == 0 else iter(buffer)
        try:
            elevenlabs.speak_stream(
                source,
                voice_id=resolved_voice,
                model_id=cfg.elevenlabs_model_id,
                on_first_chunk=on_first_chunk,
            )
            return
        except TTSError as exc:
            last_exc = exc
            if _is_quota_error(exc):
                logger.error(
                    "ElevenLabs quota exceeded — no credits left. "
                    "Upgrade at elevenlabs.io or switch tts_provider in config.json."
                )
                break
            logger.warning("ElevenLabs stream attempt %d failed: %s", attempt + 1, exc)
            time.sleep(0.4 * (attempt + 1))

    if not buffer:
        return
    logger.warning(
        "ElevenLabs stream unavailable (%s) — falling back to Cartesia",
        last_exc,
    )
    cartesia.speak_cartesia_stream(
        iter(buffer),
        _resolve_cartesia_voice(None, cfg),
        on_first_chunk=on_first_chunk,
    )


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
