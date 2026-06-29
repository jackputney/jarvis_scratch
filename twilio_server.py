"""twilio_server.py — WebSocket server for Twilio Media Streams.

Bridges Twilio mulaw audio to Jarvis voice sessions: VAD → STT → voice lane →
telephony TTS back to the caller. Runs alongside the Flask dashboard.

Start with: python twilio_server.py (or wired into main.py when Twilio is configured)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any

from adapters.twilio_audio import (
    encode_media_message,
    make_clear_message,
    make_mark_message,
    parse_media_message,
)
from adapters.twilio_call import (
    MulawUtteranceDetector,
    release_phone_call,
    run_phone_turn,
    synthesize_mulaw,
    transcribe_utterance,
    try_acquire_phone_call,
)
from config import Config

logger = logging.getLogger("jarvis.twilio")

TWILIO_PORT = 8765
PHONE_GREETING = "Hello, this is Jarvis. How can I help?"


def _env_value(key: str) -> str:
    """Read a key from .env on disk (fresh) then fall back to os.environ."""
    try:
        from dotenv import dotenv_values

        from paths import env_path

        fresh = (dotenv_values(env_path()).get(key) or "").strip()
        if fresh:
            return fresh
    except Exception:  # noqa: BLE001
        pass
    return (os.environ.get(key) or "").strip()


def resolve_media_ws_url(request_host: str, *, secure: bool) -> str:
    """Public WebSocket URL Twilio should connect to for Media Streams."""
    explicit = _env_value("TWILIO_MEDIA_WS_URL")
    if "<ngrok" in explicit:
        logger.warning("TWILIO_MEDIA_WS_URL is still a placeholder — set your real wss:// URL in .env")
        explicit = ""
    if explicit:
        return explicit
    ws_scheme = "wss" if secure else "ws"
    host = (request_host or "localhost").split(":")[0]
    port = int(_env_value("TWILIO_WS_PORT") or TWILIO_PORT)
    return f"{ws_scheme}://{host}:{port}"


class PhoneCallSession:
    """One Twilio Media Stream — session-aware turn loop without a wake word."""

    def __init__(self, websocket: Any, *, peer: str = "") -> None:
        self._ws = websocket
        self._peer = peer
        self._cfg = Config.load()
        self._detector = MulawUtteranceDetector(self._cfg)
        self._stream_sid: str | None = None
        self._call_sid: str | None = None
        self._voice_session_id: str | None = None
        self._turn_lock = asyncio.Lock()
        self._closed = False
        self._twilio_confirmed = False

    async def handle_message(self, msg: dict[str, Any]) -> None:
        event = msg.get("event")

        if event == "connected":
            self._twilio_confirmed = True
            logger.info(
                "📞 Twilio media stream ready (peer=%s protocol=%s)",
                self._peer,
                msg.get("protocol"),
            )

        elif event == "start":
            meta = msg.get("start", {})
            self._stream_sid = msg.get("streamSid") or meta.get("streamSid")
            self._call_sid = meta.get("callSid")
            if not self._call_sid or not try_acquire_phone_call(self._call_sid):
                logger.warning("Rejecting call %s — another call is active", self._call_sid)
                await self._ws.close()
                self._closed = True
                return
            from tools import phone as phone_tools

            phone_tools.set_active_call_sid(self._call_sid)
            media_format = meta.get("mediaFormat", {})
            logger.info(
                "📞 Stream started: sid=%s call=%s format=%s/%sHz",
                self._stream_sid,
                self._call_sid,
                media_format.get("encoding"),
                media_format.get("sampleRate"),
            )
            await self._speak(PHONE_GREETING)

        elif event == "media":
            if self._closed or not self._stream_sid:
                return
            mulaw = parse_media_message(msg)
            utterance_pcm = self._detector.feed(mulaw)
            if utterance_pcm:
                asyncio.create_task(self._handle_utterance(utterance_pcm))

        elif event == "mark":
            mark_name = msg.get("mark", {}).get("name", "")
            logger.debug("Playback mark reached: %s", mark_name)

        elif event == "stop":
            logger.info("Stream stopped: call=%s", self._call_sid)
            self._closed = True

    async def _handle_utterance(self, pcm_bytes: bytes) -> None:
        async with self._turn_lock:
            if self._closed or not self._stream_sid:
                return
            text = await asyncio.to_thread(transcribe_utterance, pcm_bytes, self._cfg)
            if not text:
                return
            logger.info("📞 Caller said: %r", text)
            result = await asyncio.to_thread(
                run_phone_turn, text, self._cfg, self._voice_session_id,
            )
            self._voice_session_id = result.get("session_id") or self._voice_session_id
            reply = (result.get("reply") or "").strip()
            if result.get("capped"):
                reply = reply or "I've hit today's budget cap."
            if reply:
                logger.info("📞 Jarvis reply: %s", reply[:120])
                await self._speak(reply)
            if self._voice_session_id:
                from orchestrator.runtime import get_session_store

                get_session_store().mark_idle(self._voice_session_id)

    async def _speak(self, text: str) -> None:
        if not self._stream_sid or self._closed:
            return
        try:
            mulaw = await asyncio.to_thread(synthesize_mulaw, text, self._cfg)
        except Exception:  # noqa: BLE001 — never let a TTS error drop the call
            logger.exception("Phone TTS failed — keeping call open")
            return
        if not mulaw:
            logger.warning("Phone TTS produced no audio — reply not spoken")
            return
        await send_audio_to_caller(self._ws, self._stream_sid, mulaw)

    async def close(self) -> None:
        self._closed = True
        if self._voice_session_id:
            from orchestrator.runtime import get_session_store

            get_session_store().close(self._voice_session_id)
        if self._call_sid:
            release_phone_call(self._call_sid)
            from tools import phone as phone_tools

            phone_tools.set_active_call_sid("")
        if self._call_sid:
            release_phone_call(self._call_sid)
            from tools import phone as phone_tools

            phone_tools.set_active_call_sid("")
        if self._twilio_confirmed:
            logger.info("📞 Twilio call ended (call=%s)", self._call_sid)
        else:
            logger.debug(
                "WebSocket closed before Twilio handshake (peer=%s) — "
                "usually an ngrok probe, not a phone call",
                self._peer,
            )


async def handle_media_stream(websocket) -> None:
    """Handle a single Twilio Media Stream WebSocket connection."""
    peer = getattr(websocket, "remote_address", None) or "unknown"
    session = PhoneCallSession(websocket, peer=str(peer))
    try:
        async for raw in websocket:
            msg = json.loads(raw)
            await session.handle_message(msg)
            if session._closed:
                break
    except Exception:
        logger.exception("Error in Twilio WebSocket handler (peer=%s)", peer)
    finally:
        await session.close()


async def send_audio_to_caller(
    websocket,
    stream_sid: str,
    mulaw_audio: bytes,
) -> None:
    """Stream mulaw audio back to the caller through Twilio."""
    await websocket.send(encode_media_message(mulaw_audio, stream_sid))


async def clear_caller_audio(websocket, stream_sid: str) -> None:
    """Interrupt any buffered audio on Twilio's side (barge-in)."""
    await websocket.send(make_clear_message(stream_sid))


async def mark_audio(websocket, stream_sid: str, name: str) -> None:
    """Send a mark to track when audio finishes playing."""
    await websocket.send(make_mark_message(stream_sid, name))


def build_twiml_response(websocket_url: str) -> str:
    """Return TwiML XML that connects a call to our WebSocket server."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{websocket_url}" />'
        "</Connect>"
        "</Response>"
    )


def _get_twiml_route():
    """Create a Flask blueprint for the TwiML webhook endpoint."""
    from flask import Blueprint, Response, request

    bp = Blueprint("twilio", __name__)

    @bp.route("/twilio/voice", methods=["POST"])
    def twilio_voice():
        host = request.headers.get("X-Forwarded-Host") or request.host
        secure = bool(
            request.is_secure
            or request.headers.get("X-Forwarded-Proto") == "https"
        )
        ws_url = resolve_media_ws_url(host, secure=secure)
        logger.info("📞 TwiML voice webhook → stream %s", ws_url)
        twiml = build_twiml_response(ws_url)
        return Response(twiml, content_type="application/xml")

    return bp


def twilio_configured() -> bool:
    cfg = Config.load()
    return bool((cfg.twilio_account_sid or "").strip() and (cfg.twilio_auth_token or "").strip())


def start_twilio_services() -> None:
    """Start the Media Streams WebSocket server on a background thread."""
    if not twilio_configured():
        return
    if getattr(start_twilio_services, "_started", False):
        return
    start_twilio_services._started = True  # type: ignore[attr-defined]

    def _run() -> None:
        try:
            asyncio.run(run_websocket_server())
        except Exception:  # noqa: BLE001
            logger.exception("Twilio WebSocket server exited")

    threading.Thread(target=_run, daemon=True, name="jarvis-twilio-ws").start()
    logger.info("Twilio WebSocket server thread started (port %d)", TWILIO_PORT)


async def run_websocket_server(host: str = "0.0.0.0", port: int = TWILIO_PORT) -> None:
    """Start the WebSocket server for Twilio Media Streams."""
    try:
        import websockets
    except ImportError:
        logger.error("websockets package not installed. Run: pip install websockets")
        return

    logging.getLogger("websockets").setLevel(logging.WARNING)

    logger.info("Twilio WebSocket server listening on ws://%s:%d", host, port)
    async with websockets.serve(
        handle_media_stream,
        host,
        port,
        ping_interval=20,
        ping_timeout=20,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Starting Twilio WebSocket server on port {TWILIO_PORT}...")
    print("Set TWILIO_MEDIA_WS_URL to your public wss URL (e.g. ngrok → this port)")
    print("Configure Twilio voice webhook POST to https://<tunnel>/twilio/voice")
    asyncio.run(run_websocket_server())
