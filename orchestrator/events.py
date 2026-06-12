"""Thread-safe event bus for orchestrator subscribers (Phase 1)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

Handler = Callable[[str, dict[str, Any]], None]


class EventBus:
    """Simple pub/sub — UI, dashboard WS, TTS, and loggers subscribe here."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> None:
        with self._lock:
            self._handlers.append(handler)

    def emit(self, event: str, **payload: Any) -> None:
        with self._lock:
            handlers = list(self._handlers)
        for handler in handlers:
            handler(event, payload)
