"""Outbound phone calls via Twilio REST API (cross-platform HTTP, no OS branches)."""

from __future__ import annotations

import logging
import os
import re

import requests

logger = logging.getLogger("jarvis.tools.phone")

E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")
API_TIMEOUT = 15
_active_call_sid: str = ""


def _creds() -> tuple[str, str, str] | None:
    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (os.environ.get("TWILIO_PHONE_NUMBER") or "").strip()
    if not sid or not token or not from_num:
        return None
    return sid, token, from_num


def _twilio(method: str, path: str, **kwargs) -> tuple[str | None, dict]:
    creds = _creds()
    if not creds:
        return "Error: Twilio not configured.", {}
    sid, token, _ = creds
    try:
        resp = requests.request(
            method, f"https://api.twilio.com/2010-04-01/Accounts/{sid}{path}",
            auth=(sid, token), timeout=API_TIMEOUT, **kwargs,
        )
        data = resp.json()
        if resp.status_code >= 400:
            return f"Call error: {data.get('message', resp.text)}", data
        return None, data
    except Exception as exc:  # noqa: BLE001
        return f"Call error: {exc}", {}


def _resolve_sid(call_sid: str) -> str:
    return (call_sid or "").strip() or _active_call_sid


def make_call(to: str, purpose: str = "") -> str:
    """Initiate an outbound call. ``to`` must be E.164 (e.g. +14155551234)."""
    if purpose:
        logger.info("Outbound call purpose: %s", purpose)
    number = (to or "").strip()
    if not E164_RE.match(number):
        return f"Refused: {to!r} is not valid E.164 format (e.g. +14155551234)."
    creds = _creds()
    if not creds:
        return (
            "Error: Twilio not configured. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER."
        )
    voice_url = (os.environ.get("TWILIO_VOICE_URL") or "").strip()
    if not voice_url:
        return "Error: TWILIO_VOICE_URL not configured (TwiML webhook for outbound calls)."
    _, _, from_num = creds
    err, data = _twilio("POST", "/Calls.json", data={"To": number, "From": from_num, "Url": voice_url})
    if err:
        return err
    global _active_call_sid
    _active_call_sid = data.get("sid", "")
    return f"Call initiated to {number} (status: {data.get('status', 'unknown')}, sid: {_active_call_sid})."


def end_call(call_sid: str = "") -> str:
    """Hang up the active call or a specific call by SID."""
    target = _resolve_sid(call_sid)
    if not target:
        return "Error: No active call SID. Pass call_sid or place a call first."
    err, data = _twilio("POST", f"/Calls/{target}.json", data={"Status": "completed"})
    if err:
        return err
    return f"Call {target} ended (status: {data.get('status', 'completed')})."


def get_call_status(call_sid: str = "") -> str:
    """Return current call status (ringing, in-progress, completed, etc.)."""
    target = _resolve_sid(call_sid)
    if not target:
        return "Error: No active call SID. Pass call_sid or place a call first."
    err, data = _twilio("GET", f"/Calls/{target}.json")
    if err:
        return err
    return f"Call {target}: {data.get('status', 'unknown')}."
