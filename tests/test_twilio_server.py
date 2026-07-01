"""Tests for twilio_server.py — WebSocket server and TwiML generation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from twilio_server import (
    PHONE_MAX_CONSECUTIVE_MISSES,
    PhoneCallSession,
    build_twiml_response,
    clear_caller_audio,
    mark_audio,
    resolve_media_ws_url,
    send_audio_to_caller,
)


class TestBuildTwiml:
    def test_contains_stream_element(self):
        xml = build_twiml_response("wss://example.com/media")
        assert "<Stream" in xml
        assert 'url="wss://example.com/media"' in xml

    def test_contains_connect_wrapper(self):
        xml = build_twiml_response("wss://test.ngrok.io/media-stream")
        assert "<Connect>" in xml
        assert "</Connect>" in xml

    def test_valid_xml_structure(self):
        xml = build_twiml_response("wss://x.com/ws")
        assert xml.startswith("<?xml")
        assert "<Response>" in xml
        assert "</Response>" in xml


class TestMessageBuilders:
    """Test the JSON message builders for Twilio WebSocket protocol."""

    def test_clear_message(self):
        import asyncio

        sent = []

        class FakeWS:
            async def send(self, data):
                sent.append(data)

        ws = FakeWS()
        asyncio.run(clear_caller_audio(ws, "stream123"))
        msg = json.loads(sent[0])
        assert msg["event"] == "clear"
        assert msg["streamSid"] == "stream123"

    def test_mark_message(self):
        import asyncio

        sent = []

        class FakeWS:
            async def send(self, data):
                sent.append(data)

        ws = FakeWS()
        asyncio.run(mark_audio(ws, "stream456", "end-of-greeting"))
        msg = json.loads(sent[0])
        assert msg["event"] == "mark"
        assert msg["streamSid"] == "stream456"
        assert msg["mark"]["name"] == "end-of-greeting"

    def test_send_audio(self):
        import asyncio
        import base64

        sent = []

        class FakeWS:
            async def send(self, data):
                sent.append(data)

        ws = FakeWS()
        audio = b"\x00\x01\x02\x03"
        asyncio.run(send_audio_to_caller(ws, "streamABC", audio))
        msg = json.loads(sent[0])
        assert msg["event"] == "media"
        assert msg["streamSid"] == "streamABC"
        decoded = base64.b64decode(msg["media"]["payload"])
        assert decoded == audio


class TestTwimlRoute:
    def test_blueprint_creates(self):
        from twilio_server import _get_twiml_route
        bp = _get_twiml_route()
        assert bp.name == "twilio"


class TestMediaWsUrl:
    def test_explicit_env_override(self, monkeypatch):
        import twilio_server

        monkeypatch.setattr(
            twilio_server,
            "_env_value",
            lambda key: "wss://tunnel.example/ws" if key == "TWILIO_MEDIA_WS_URL" else "",
        )
        assert resolve_media_ws_url("ignored:7777", secure=False) == "wss://tunnel.example/ws"

    def test_derived_from_host_and_port(self, monkeypatch):
        import twilio_server

        monkeypatch.setattr(
            twilio_server,
            "_env_value",
            lambda key: "8765" if key == "TWILIO_WS_PORT" else "",
        )
        assert resolve_media_ws_url("myhost.ngrok.io", secure=True) == "wss://myhost.ngrok.io:8765"


class TestPhoneCallSessionSafety:
    def test_halt_on_start_escalates(self, monkeypatch):
        import asyncio
        from tools import phone as phone_tools

        phone_tools.reset_phone_safety_state_for_tests()
        cfg = MagicMock()
        cfg.phone_autonomous_enabled = False
        monkeypatch.setattr("twilio_server.Config.load", lambda: cfg)
        monkeypatch.setattr("twilio_server.try_acquire_phone_call", lambda _sid: True)

        session = PhoneCallSession(AsyncMock(), peer="test")
        session._escalate_or_end = AsyncMock()
        session._speak = AsyncMock()

        async def _run():
            await session.handle_message({
                "event": "start",
                "streamSid": "MZ1",
                "start": {"callSid": "CAhalt", "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}},
            })

        asyncio.run(_run())
        session._escalate_or_end.assert_awaited_once()
        session._speak.assert_not_awaited()

    def test_consecutive_misses_escalate(self, monkeypatch):
        import asyncio
        from tools import phone as phone_tools

        phone_tools.reset_phone_safety_state_for_tests()
        cfg = MagicMock()
        cfg.phone_autonomous_enabled = True
        monkeypatch.setattr("twilio_server.Config.load", lambda: cfg)

        session = PhoneCallSession(AsyncMock(), peer="test")
        session._stream_sid = "MZ1"
        session._call_sid = "CA1"
        session._escalate_or_end = AsyncMock()
        session._consecutive_misses = PHONE_MAX_CONSECUTIVE_MISSES - 1

        async def _run():
            with patch("twilio_server.transcribe_utterance", return_value=None):
                await session._handle_utterance(b"\x00" * 100)

        asyncio.run(_run())
        session._escalate_or_end.assert_awaited_once()

    def test_turn_escalate_flag_transfers(self, monkeypatch):
        import asyncio
        from tools import phone as phone_tools

        phone_tools.reset_phone_safety_state_for_tests()
        cfg = MagicMock()
        cfg.phone_autonomous_enabled = True
        monkeypatch.setattr("twilio_server.Config.load", lambda: cfg)

        session = PhoneCallSession(AsyncMock(), peer="test")
        session._stream_sid = "MZ1"
        session._call_sid = "CA2"
        session._escalate_or_end = AsyncMock()
        session._speak = AsyncMock()

        async def _run():
            with patch("twilio_server.transcribe_utterance", return_value="talk to a person"):
                with patch(
                    "twilio_server.run_phone_turn",
                    return_value={
                        "reply": "Connecting you.",
                        "escalate": True,
                        "session_id": None,
                        "capped": False,
                    },
                ):
                    await session._handle_utterance(b"\x00" * 100)

        asyncio.run(_run())
        session._escalate_or_end.assert_awaited_once_with("Connecting you.")
        session._speak.assert_not_awaited()
