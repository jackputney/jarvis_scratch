"""Outbound phone calls via Twilio REST API (cross-platform HTTP, no OS branches)."""

from __future__ import annotations

import logging
import os
import re
import threading

import requests

logger = logging.getLogger("jarvis.tools.phone")

E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")
API_TIMEOUT = 15
_active_call_sid: str = ""

_halt_lock = threading.Lock()
_global_halt_autonomous = False
_per_call_halt: set[str] = set()

ESCALATION_PHRASES: tuple[str, ...] = (
    "talk to a person",
    "talk to someone",
    "speak to a person",
    "speak to someone",
    "speak to a human",
    "talk to a human",
    "real person",
    "human please",
    "transfer me",
    "transfer my call",
    "connect me to",
    "operator",
    "representative",
    "customer service",
    "live agent",
)


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


def set_active_call_sid(call_sid: str) -> None:
    """Track the active Media Stream call for tool hangup/status."""
    global _active_call_sid
    _active_call_sid = (call_sid or "").strip()


def get_active_call_sid() -> str:
    return _active_call_sid


def _resolve_sid(call_sid: str) -> str:
    return (call_sid or "").strip() or _active_call_sid


def fallback_number() -> str:
    return (os.environ.get("TWILIO_FALLBACK_NUMBER") or "").strip()


def build_transfer_twiml(number: str, *, message: str = "Please hold while I connect you.") -> str:
    safe_num = (number or "").strip()
    msg = (message or "").strip() or "Please hold."
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Say>{msg}</Say>"
        f"<Dial>{safe_num}</Dial>"
        "</Response>"
    )


def caller_requests_human(text: str) -> bool:
    """True when the caller explicitly asks for a human."""
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    return any(phrase in lowered for phrase in ESCALATION_PHRASES)


def is_phone_autonomous_halted(call_sid: str = "") -> bool:
    """Global or per-call halt — stops autonomous phone turns."""
    sid = (call_sid or "").strip()
    with _halt_lock:
        if _global_halt_autonomous:
            return True
        return sid in _per_call_halt if sid else False


def halt_phone_autonomous(*, call_sid: str = "", persist: bool = False) -> str:
    """Halt autonomous phone actions; optionally transfer the active call."""
    global _global_halt_autonomous
    sid = (call_sid or "").strip() or _active_call_sid
    with _halt_lock:
        _global_halt_autonomous = True
        if sid:
            _per_call_halt.add(sid)
    if persist:
        try:
            from config import Config

            Config.update_persisted({"phone_autonomous_enabled": False})
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist phone_autonomous_enabled=false")
    if sid:
        return escalate_to_human(sid, reason="autonomous halt")
    return "Phone autonomous mode halted (no active call to transfer)."


def resume_phone_autonomous(*, persist: bool = False) -> str:
    """Clear halt flags so new phone calls may run autonomously."""
    global _global_halt_autonomous
    with _halt_lock:
        _global_halt_autonomous = False
        _per_call_halt.clear()
    if persist:
        try:
            from config import Config

            Config.update_persisted({"phone_autonomous_enabled": True})
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist phone_autonomous_enabled=true")
    return "Phone autonomous mode resumed."


def phone_autonomous_allowed(cfg: object | None = None, call_sid: str = "") -> bool:
    """Config + runtime halt gate for the phone turn loop."""
    if is_phone_autonomous_halted(call_sid):
        return False
    if cfg is not None and not getattr(cfg, "phone_autonomous_enabled", True):
        return False
    return True


def reset_phone_safety_state_for_tests() -> None:
    global _global_halt_autonomous, _active_call_sid
    with _halt_lock:
        _global_halt_autonomous = False
        _per_call_halt.clear()
    _active_call_sid = ""


def escalate_to_human(call_sid: str = "", reason: str = "") -> str:
    """Transfer the caller to TWILIO_FALLBACK_NUMBER, or end the call if unset."""
    target = _resolve_sid(call_sid)
    if not target:
        return "Error: No active call SID to transfer."
    if reason:
        logger.info("📞 Escalating call %s to human (%s)", target, reason)
    fallback = fallback_number()
    if not fallback:
        logger.warning("TWILIO_FALLBACK_NUMBER not set — ending call %s", target)
        return end_call(target)
    if not E164_RE.match(fallback):
        return f"Error: TWILIO_FALLBACK_NUMBER {fallback!r} is not valid E.164."
    twiml = build_transfer_twiml(fallback)
    err, data = _twilio("POST", f"/Calls/{target}.json", data={"Twiml": twiml})
    if err:
        return err
    return (
        f"Call {target} transferring to {fallback} "
        f"(status: {data.get('status', 'unknown')})."
    )


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
