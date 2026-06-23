"""Dashboard tool-run confirmation — two-step approval for high-risk tools."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}
_EXPIRY_SEC = 60.0


def create_pending(tool: str, inputs: dict) -> str:
    confirm_id = str(uuid.uuid4())
    with _lock:
        _purge_expired_locked()
        _pending[confirm_id] = {
            "tool": tool,
            "inputs": dict(inputs),
            "created_at": time.time(),
        }
    return confirm_id


def consume(confirm_id: str) -> dict[str, Any] | None:
    with _lock:
        _purge_expired_locked()
        entry = _pending.pop(confirm_id, None)
    if entry is None:
        return None
    if time.time() - entry["created_at"] > _EXPIRY_SEC:
        return None
    return entry


def _purge_expired_locked() -> None:
    now = time.time()
    for cid in [k for k, v in _pending.items() if now - v["created_at"] > _EXPIRY_SEC]:
        del _pending[cid]


def reset_for_tests() -> None:
    """Clear pending dashboard tool-run confirms between tests."""
    with _lock:
        _pending.clear()
