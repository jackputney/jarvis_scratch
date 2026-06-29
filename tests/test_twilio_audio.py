"""Twilio audio adapter — conversion and message helpers."""

from __future__ import annotations

import base64
import json

import pytest

from adapters import twilio_audio as ta


def test_mulaw_to_pcm_upsamples():
    # 160 mulaw samples @ 8kHz → ~320 PCM samples @ 16kHz, 2 bytes each → ~640 bytes
    # ratecv may add a few extra bytes of filter state
    mulaw = bytes([0xFF] * 160)
    pcm = ta.mulaw_to_pcm(mulaw)
    assert isinstance(pcm, bytes)
    assert len(pcm) > 160 * 2


def test_pcm_to_mulaw_downsamples():
    # 320 bytes = 160 PCM samples @ 16kHz → ~80 mulaw samples @ 8kHz
    pcm = bytes([0x00, 0x10] * 160)
    mulaw = ta.pcm_to_mulaw(pcm)
    assert isinstance(mulaw, bytes)
    assert len(mulaw) < len(pcm)


def test_round_trip_preserves_approximate_length():
    original = bytes(range(256)) * 4
    round_trip = ta.pcm_to_mulaw(ta.mulaw_to_pcm(original))
    assert abs(len(round_trip) - len(original)) < len(original) * 0.05


def test_parse_media_message_decodes_payload():
    raw = b"\xff\xfe"
    msg = {"event": "media", "media": {"payload": base64.b64encode(raw).decode()}}
    assert ta.parse_media_message(msg) == raw


def test_parse_media_message_empty_payload():
    assert ta.parse_media_message({"media": {}}) == b""


def test_encode_media_message_round_trip():
    audio = b"\x7f\x80\xaa"
    stream_sid = "MZ123"
    encoded = ta.encode_media_message(audio, stream_sid)
    parsed = json.loads(encoded)
    assert parsed["event"] == "media"
    assert parsed["streamSid"] == stream_sid
    assert base64.b64decode(parsed["media"]["payload"]) == audio


def test_make_clear_message():
    msg = json.loads(ta.make_clear_message("MZ456"))
    assert msg == {"event": "clear", "streamSid": "MZ456"}


def test_make_mark_message():
    msg = json.loads(ta.make_mark_message("MZ789", "done"))
    assert msg["event"] == "mark"
    assert msg["streamSid"] == "MZ789"
    assert msg["mark"]["name"] == "done"


@pytest.mark.skipif(
    not hasattr(__import__("audioop"), "ulaw2lin"),
    reason="audioop unavailable",
)
def test_mulaw_pcm_known_silence():
    """Silence mulaw byte 0xFF decodes to near-zero PCM samples."""
    pcm = ta.mulaw_to_pcm(bytes([0xFF] * 8))
    assert all(b in (0x00, 0xFF, 0xFE, 0x01, 0x02) for b in pcm)
