"""Shutdown handling for terminal/Qt launches."""

from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import main


def test_request_ui_shutdown_interrupts_pipeline_and_quits(monkeypatch):
    calls: list[object] = []
    stop_event = threading.Event()

    monkeypatch.setitem(
        sys.modules,
        "pipeline",
        SimpleNamespace(request_interrupt=lambda: calls.append("interrupt")),
    )

    class App:
        def quit(self) -> None:
            calls.append("quit")

    main._request_ui_shutdown(
        stop_event,
        graceful_shutdown=lambda: calls.append("graceful"),
        app=App(),
        force_exit=lambda: calls.append("force"),
        timer_factory=lambda ms, cb: calls.append(("timer", ms)),
    )

    assert stop_event.is_set()
    assert calls == ["interrupt", "graceful", "quit", ("timer", 1500)]
