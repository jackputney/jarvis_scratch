"""Twilio phone call loop — mulaw capture, STT, voice lane, telephony TTS."""

from __future__ import annotations

import audioop
import logging
import threading
from typing import Any

from adapters.audio_io import FRAME_DURATION_MS, frame_is_speech
from adapters.twilio_audio import MULAW_RATE, PCM_RATE, mulaw_to_pcm, pcm_to_mulaw
from config import Config

logger = logging.getLogger("jarvis.adapters.twilio_call")

MULAW_FRAME_BYTES = int(MULAW_RATE * FRAME_DURATION_MS / 1000)
PCM_FRAME_BYTES = int(PCM_RATE * FRAME_DURATION_MS / 1000) * 2
MAX_UTTERANCE_SEC = 30
MAX_WAIT_SPEECH_FRAMES = int(8000 / FRAME_DURATION_MS)

_call_lock = threading.Lock()
_active_phone_call_sid: str | None = None


def try_acquire_phone_call(call_sid: str) -> bool:
    """Allow only one active Media Stream at a time (v1)."""
    global _active_phone_call_sid
    sid = (call_sid or "").strip()
    if not sid:
        return False
    with _call_lock:
        if _active_phone_call_sid and _active_phone_call_sid != sid:
            return False
        _active_phone_call_sid = sid
        return True


def release_phone_call(call_sid: str) -> None:
    global _active_phone_call_sid
    sid = (call_sid or "").strip()
    with _call_lock:
        if _active_phone_call_sid == sid:
            _active_phone_call_sid = None


class MulawUtteranceDetector:
    """VAD on inbound mulaw — yields one PCM 16 kHz utterance when trailing silence ends."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._mulaw_pending = bytearray()
        self._frames: list[bytes] = []
        self._silent_frames = 0
        self._speech_started = False
        self._frame_idx = 0
        self._silence_limit = max(10, int(cfg.vad_silence_ms / FRAME_DURATION_MS))
        self._min_frames = max(15, int(cfg.vad_min_capture_ms / FRAME_DURATION_MS))
        self._max_frames = int(MAX_UTTERANCE_SEC * 1000 / FRAME_DURATION_MS)

    def reset(self) -> None:
        self._mulaw_pending.clear()
        self._frames.clear()
        self._silent_frames = 0
        self._speech_started = False
        self._frame_idx = 0

    def feed(self, mulaw_chunk: bytes) -> bytes | None:
        if not mulaw_chunk:
            return None
        self._mulaw_pending.extend(mulaw_chunk)
        while len(self._mulaw_pending) >= MULAW_FRAME_BYTES:
            raw = bytes(self._mulaw_pending[:MULAW_FRAME_BYTES])
            del self._mulaw_pending[:MULAW_FRAME_BYTES]
            pcm_frame = mulaw_to_pcm(raw)
            if len(pcm_frame) < PCM_FRAME_BYTES:
                if not pcm_frame:
                    continue
                pcm_frame += b"\x00" * (PCM_FRAME_BYTES - len(pcm_frame))
            self._frame_idx += 1
            if self._frame_idx > self._max_frames:
                return self._finish()
            is_speech = frame_is_speech(pcm_frame, self._cfg)
            if is_speech:
                self._speech_started = True
                self._silent_frames = 0
                self._frames.append(pcm_frame)
            elif self._speech_started:
                self._silent_frames += 1
                self._frames.append(pcm_frame)
                if (
                    self._frame_idx >= self._min_frames
                    and self._silent_frames > self._silence_limit
                ):
                    return self._finish()
            else:
                self._frames.append(pcm_frame)
                if len(self._frames) > 8:
                    self._frames.pop(0)
                if self._frame_idx >= MAX_WAIT_SPEECH_FRAMES:
                    self.reset()
        return None

    def _finish(self) -> bytes | None:
        if not self._speech_started:
            self.reset()
            return None
        audio = b"".join(self._frames)
        self.reset()
        return audio


def transcribe_utterance(pcm_bytes: bytes, cfg: Config) -> str | None:
    from pipeline import _transcribe

    if len(pcm_bytes) < PCM_FRAME_BYTES * 3:
        return None
    try:
        text = (_transcribe(pcm_bytes, cfg) or "").strip()
    except Exception:  # noqa: BLE001
        logger.exception("Phone STT failed")
        return None
    return text or None


def _elevenlabs_pcm_16k(text: str, cfg: Config) -> bytes:
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=cfg.elevenlabs_api_key.strip())
    stream = client.text_to_speech.convert(
        voice_id=cfg.elevenlabs_voice_id,
        text=text,
        model_id=cfg.elevenlabs_model_id,
        output_format="pcm_16000",
    )
    return b"".join(chunk for chunk in stream if chunk)


def _cartesia_pcm_16k(text: str, cfg: Config) -> bytes:
    from tts.cartesia import SAMPLE_RATE as CARTESIA_RATE
    from tts.cartesia import _iter_cartesia_audio

    api_key = (cfg.cartesia_api_key or "").strip()
    if not api_key:
        return b""
    pcm_44k = b"".join(_iter_cartesia_audio(text, cfg.cartesia_voice_id, api_key))
    if not pcm_44k:
        return b""
    pcm_16k, _ = audioop.ratecv(pcm_44k, 2, 1, CARTESIA_RATE, PCM_RATE, None)
    return pcm_16k


def synthesize_pcm_16k(text: str, cfg: Config) -> bytes:
    """Synthesize reply audio at 16 kHz mono PCM for telephony.

    Tries the configured provider, then falls back to the other cloud provider
    (e.g. ElevenLabs quota exhausted → Cartesia) so a single provider outage
    never silences the phone agent.
    """
    from tts.router import effective_tts_provider

    cleaned = (text or "").strip()
    if not cleaned:
        return b""

    provider = effective_tts_provider(cfg)
    has_eleven = bool((cfg.elevenlabs_api_key or "").strip())
    has_cartesia = bool((cfg.cartesia_api_key or "").strip())

    order: list[str] = []
    if provider == "elevenlabs":
        order = ["elevenlabs", "cartesia"]
    else:
        order = ["cartesia", "elevenlabs"]

    for name in order:
        try:
            if name == "elevenlabs" and has_eleven:
                pcm = _elevenlabs_pcm_16k(cleaned, cfg)
            elif name == "cartesia" and has_cartesia:
                pcm = _cartesia_pcm_16k(cleaned, cfg)
            else:
                continue
            if pcm:
                return pcm
        except Exception as exc:  # noqa: BLE001
            logger.warning("Phone TTS via %s failed (%s) — trying fallback", name, exc)

    logger.warning("No working cloud TTS — phone reply not spoken")
    return b""


def synthesize_mulaw(text: str, cfg: Config) -> bytes:
    pcm = synthesize_pcm_16k(text, cfg)
    if not pcm:
        return b""
    return pcm_to_mulaw(pcm)


def run_phone_turn(
    text: str,
    cfg: Config,
    session_id: str | None = None,
    *,
    call_sid: str | None = None,
) -> dict[str, Any]:
    """Submit one utterance to the voice lane (no local speaker TTS).

    Applies phone safety: halt gate, human-escalation phrases, and CommandSource.PHONE
    so side-effecting tools are blocked in the pipeline.
    """
    from orchestrator.runtime import get_lane_manager, get_orchestrator
    from orchestrator.types import Command, CommandSource
    from tools import phone as phone_tools

    sid = (call_sid or phone_tools.get_active_call_sid() or "").strip()

    if not phone_tools.phone_autonomous_allowed(cfg, sid):
        return {
            "reply": "Connecting you to someone who can help.",
            "session_id": session_id,
            "capped": False,
            "escalate": True,
            "escalate_reason": "halt",
        }

    if phone_tools.caller_requests_human(text):
        return {
            "reply": "Connecting you to someone who can help.",
            "session_id": session_id,
            "capped": False,
            "escalate": True,
            "escalate_reason": "caller_request",
        }

    lane_manager = get_lane_manager()
    voice_lane = lane_manager.voice
    orchestrator = get_orchestrator()

    sub = voice_lane.submit(
        Command(text=text, source=CommandSource.PHONE, speak=False),
        session_id=session_id,
    )
    if not sub.accepted or not sub.job_id:
        return {
            "reply": "I'm busy right now — try again in a moment.",
            "session_id": session_id,
            "capped": False,
            "escalate": False,
        }

    job = orchestrator.wait(sub.job_id, timeout=180.0)
    if job is None:
        return {"reply": "", "session_id": session_id, "capped": False, "escalate": False}
    return {
        "reply": (job.reply or "").strip(),
        "session_id": job.session_id,
        "capped": bool(job.capped),
        "escalate": False,
    }
