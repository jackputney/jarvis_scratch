"""twilio_server.py — WebSocket server for Twilio Media Streams.

Runs alongside the Flask dashboard. Handles inbound/outbound phone calls
by bridging Twilio's mulaw audio stream to Jarvis's voice pipeline.

Start with: python twilio_server.py (or wired into main.py later)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any

logger = logging.getLogger("jarvis.twilio")

TWILIO_PORT = 8765


async def handle_media_stream(websocket) -> None:
    """Handle a single Twilio Media Stream WebSocket connection."""
    stream_sid: str | None = None
    call_sid: str | None = None
    logger.info("Twilio WebSocket connected")

    try:
        async for raw in websocket:
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                logger.info("Twilio stream connected (protocol=%s)", msg.get("protocol"))

            elif event == "start":
                meta = msg.get("start", {})
                stream_sid = msg.get("streamSid") or meta.get("streamSid")
                call_sid = meta.get("callSid")
                media_format = meta.get("mediaFormat", {})
                logger.info(
                    "Stream started: sid=%s call=%s format=%s/%sHz",
                    stream_sid, call_sid,
                    media_format.get("encoding"), media_format.get("sampleRate"),
                )

            elif event == "media":
                payload_b64 = msg.get("media", {}).get("payload", "")
                if not payload_b64:
                    continue
                mulaw_bytes = base64.b64decode(payload_b64)
                await _process_inbound_audio(mulaw_bytes, stream_sid, websocket)

            elif event == "mark":
                mark_name = msg.get("mark", {}).get("name", "")
                logger.debug("Playback mark reached: %s", mark_name)

            elif event == "stop":
                logger.info("Stream stopped: call=%s", call_sid)
                break

    except Exception:
        logger.exception("Error in Twilio WebSocket handler")
    finally:
        logger.info("Twilio WebSocket closed (call=%s)", call_sid)


async def _process_inbound_audio(
    mulaw_bytes: bytes,
    stream_sid: str | None,
    websocket,
) -> None:
    """Process an inbound audio chunk from Twilio.

    Placeholder — will be wired to STT + pipeline session once the
    session architecture lands. For now, just accumulates audio.
    """
    pass


async def send_audio_to_caller(
    websocket,
    stream_sid: str,
    mulaw_audio: bytes,
) -> None:
    """Stream mulaw audio back to the caller through Twilio."""
    payload = base64.b64encode(mulaw_audio).decode()
    msg = json.dumps({
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": payload},
    })
    await websocket.send(msg)


async def clear_caller_audio(websocket, stream_sid: str) -> None:
    """Interrupt any buffered audio on Twilio's side (barge-in)."""
    await websocket.send(json.dumps({
        "event": "clear",
        "streamSid": stream_sid,
    }))


async def mark_audio(websocket, stream_sid: str, name: str) -> None:
    """Send a mark to track when audio finishes playing."""
    await websocket.send(json.dumps({
        "event": "mark",
        "streamSid": stream_sid,
        "mark": {"name": name},
    }))


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
        scheme = "wss" if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https" else "ws"
        ws_url = f"{scheme}://{host}/media-stream"
        twiml = build_twiml_response(ws_url)
        return Response(twiml, content_type="application/xml")

    return bp


async def run_websocket_server(host: str = "0.0.0.0", port: int = TWILIO_PORT) -> None:
    """Start the WebSocket server for Twilio Media Streams."""
    try:
        import websockets
    except ImportError:
        logger.error("websockets package not installed. Run: pip install websockets")
        return

    logger.info("Twilio WebSocket server starting on ws://%s:%d", host, port)
    async with websockets.serve(handle_media_stream, host, port):
        await asyncio.Future()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Starting Twilio WebSocket server on port {TWILIO_PORT}...")
    print("Configure your Twilio webhook to POST to https://<your-ngrok>/twilio/voice")
    asyncio.run(run_websocket_server())
