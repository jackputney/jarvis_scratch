"""
tools/confirm.py — Dashboard-based tool confirmation (replaces terminal input()).

High-risk mutating tools block on a pending confirm the dashboard resolves.
The pipeline polls with short sleeps so Stop / interrupt can cancel the wait.
Auto-denies after confirm_timeout_sec if nobody clicks Allow.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable

_lock = threading.Lock()
_pending: dict[str, Any] | None = None

# Set by cancel_pending() when Stop is pressed or the pipeline cycle aborts.
_cancelled = threading.Event()


def cancel_pending() -> None:
    """Deny and release any in-flight confirm wait (called from request_interrupt)."""
    _cancelled.set()
    with _lock:
        if _pending is not None:
            _pending["decision"] = "cancel"
            _pending["event"].set()


def _clear_cancel_flag() -> None:
    _cancelled.clear()


def get_pending() -> dict[str, Any] | None:
    """Public snapshot for /api/state — no threading primitives exposed."""
    with _lock:
        if _pending is None:
            return None
        age = time.time() - _pending["created_at"]
        return {
            "id": _pending["id"],
            "tool": _pending["tool"],
            "inputs": _pending["inputs"],
            "age_sec": round(age, 1),
            "timeout_sec": _pending["timeout_sec"],
        }


def respond(confirm_id: str, allow: bool) -> bool:
    """Dashboard Allow/Deny handler. Returns True if this confirm was resolved."""
    with _lock:
        if _pending is None or _pending["id"] != confirm_id:
            return False
        _pending["decision"] = "allow" if allow else "deny"
        _pending["event"].set()
        return True


def wait_for_confirm(
    tool: str,
    inputs: dict,
    timeout_sec: int = 30,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Block until allow, deny, timeout, or cancel. Returns decision string."""
    global _pending
    _clear_cancel_flag()
    with _lock:
        if _pending is not None:
            return "deny"

    event = threading.Event()
    confirm_id = str(uuid.uuid4())
    entry = {
        "id": confirm_id,
        "tool": tool,
        "inputs": inputs,
        "created_at": time.time(),
        "timeout_sec": timeout_sec,
        "decision": None,
        "event": event,
    }
    with _lock:
        _pending = entry

    try:
        from orchestrator.runtime import get_bus
        get_bus().emit(
            "confirm.pending",
            type="confirm",
            id=confirm_id,
            tool=tool,
            inputs=inputs,
            age_sec=0.0,
            timeout_sec=timeout_sec,
        )
    except Exception:
        pass  # dashboard not running / bus unavailable — catch-up path still covers new clients

    deadline = time.time() + timeout_sec
    try:
        while time.time() < deadline:
            if cancel_check and cancel_check():
                with _lock:
                    if _pending is entry:
                        entry["decision"] = "cancel"
                return "cancel"
            if _cancelled.is_set():
                return "cancel"
            if event.wait(timeout=0.25):
                with _lock:
                    decision = entry.get("decision") or "deny"
                return decision
        return "timeout"
    finally:
        with _lock:
            if _pending is entry:
                _pending = None


def format_inputs(inputs: dict) -> str:
    """Compact display string for the dashboard modal."""
    try:
        return json.dumps(inputs, ensure_ascii=False, indent=2)
    except TypeError:
        return str(inputs)
