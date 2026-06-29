"""Tests for twilio_server.py — WebSocket server and TwiML generation."""

from __future__ import annotations

import json

from twilio_server import (
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
