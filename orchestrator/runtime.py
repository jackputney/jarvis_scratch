"""Process-wide orchestrator singleton + event bus."""

from __future__ import annotations

import threading
from typing import Any

from orchestrator.core import Orchestrator
from orchestrator.events import EventBus

_bus = EventBus()
_orchestrator: Orchestrator | None = None
_lock = threading.Lock()


def get_bus() -> EventBus:
    return _bus


def _default_process_query(
    text: str,
    cfg: Any,
    on_state=None,
    speak: bool = False,
    on_sentence=None,
) -> dict:
    import pipeline

    return pipeline.process_query(
        text, cfg, on_state=on_state, speak=speak, on_sentence=on_sentence,
    )


def _default_speak(text: str, voice_id: str | None = None) -> None:
    import pipeline

    if voice_id:
        pipeline.speak(text, voice_id=voice_id)
    else:
        pipeline.speak(text)


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    with _lock:
        if _orchestrator is None:
            from config import Config
            import events

            def _sync_legacy(event: str, payload: dict) -> None:
                if event == "pipeline.state":
                    events.set_pipeline_state(payload.get("state", "IDLE"))

            _bus.subscribe(_sync_legacy)
            _orchestrator = Orchestrator(
                bus=_bus,
                process_query=_default_process_query,
                speak=_default_speak,
                config_loader=Config.load,
            )
        return _orchestrator


def reset_for_tests() -> None:
    """Tear down the singleton so the next get_orchestrator() builds fresh."""
    global _orchestrator
    with _lock:
        if _orchestrator is not None:
            _orchestrator.shutdown()
        _orchestrator = None
