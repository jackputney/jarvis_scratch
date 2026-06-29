"""Twilio Media Streams audio conversion — pure data transforms, no I/O."""

from __future__ import annotations

import audioop
import base64
import json

MULAW_RATE = 8000
PCM_RATE = 16000
SAMPLE_WIDTH = 2


def mulaw_to_pcm(data: bytes) -> bytes:
    """Convert mulaw 8 kHz to PCM 16 kHz int16."""
    pcm_8k = audioop.ulaw2lin(data, SAMPLE_WIDTH)
    pcm_16k, _ = audioop.ratecv(pcm_8k, SAMPLE_WIDTH, 1, MULAW_RATE, PCM_RATE, None)
    return pcm_16k


def pcm_to_mulaw(data: bytes) -> bytes:
    """Convert PCM 16 kHz int16 to mulaw 8 kHz."""
    pcm_8k, _ = audioop.ratecv(data, SAMPLE_WIDTH, 1, PCM_RATE, MULAW_RATE, None)
    return audioop.lin2ulaw(pcm_8k, SAMPLE_WIDTH)


def parse_media_message(msg: dict) -> bytes:
    """Extract and base64-decode audio from a Twilio WebSocket media message."""
    payload = msg.get("media", {}).get("payload", "")
    return base64.b64decode(payload)


def encode_media_message(audio: bytes, stream_sid: str) -> str:
    """Wrap mulaw audio as a base64-encoded Twilio media JSON message."""
    return json.dumps({
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": base64.b64encode(audio).decode("ascii")},
    })


def make_clear_message(stream_sid: str) -> str:
    """Return the JSON clear message to interrupt Twilio playback (barge-in)."""
    return json.dumps({"event": "clear", "streamSid": stream_sid})


def make_mark_message(stream_sid: str, name: str) -> str:
    """Return the JSON mark message to track playback completion."""
    return json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": name}})
