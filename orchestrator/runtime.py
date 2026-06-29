"""Process-wide orchestrator singleton + event bus."""

from __future__ import annotations

import threading
from typing import Any

from orchestrator.core import Orchestrator
from orchestrator.events import EventBus
from orchestrator.lanes import BackgroundLane, LaneManager, VoiceLane
from orchestrator.session import SessionStore

_bus = EventBus()
_orchestrator: Orchestrator | None = None
_session_store: SessionStore | None = None
_lane_manager: LaneManager | None = None

# Separate non-reentrant locks per singleton to avoid deadlock.
_orc_lock = threading.Lock()
_store_lock = threading.Lock()
_lane_lock = threading.Lock()


def get_bus() -> EventBus:
    return _bus


def _default_process_query(
    text: str,
    cfg: Any,
    on_state=None,
    speak: bool = False,
    on_sentence=None,
    session_id: str | None = None,
) -> dict:
    import pipeline

    return pipeline.process_query(
        text,
        cfg,
        on_state=on_state,
        speak=speak,
        on_sentence=on_sentence,
        session_id=session_id,
    )


def _default_speak(text: str, voice_id: str | None = None) -> None:
    import pipeline

    if voice_id:
        pipeline.speak(text, voice_id=voice_id)
    else:
        pipeline.speak(text)


def get_session_store() -> SessionStore:
    global _session_store
    with _store_lock:
        if _session_store is None:
            _session_store = SessionStore()
        return _session_store


def get_lane_manager() -> LaneManager:
    global _lane_manager
    # Acquire dependencies outside _lane_lock to avoid nested lock acquisition.
    store = get_session_store()
    orc = get_orchestrator()
    with _lane_lock:
        if _lane_manager is None:
            voice = VoiceLane(orchestrator=orc, store=store, bus=_bus)
            background = BackgroundLane(store=store, bus=_bus)
            _lane_manager = LaneManager(voice=voice, background=background)
        return _lane_manager


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    # Check without lock first (fast path).
    if _orchestrator is not None:
        return _orchestrator
    with _orc_lock:
        if _orchestrator is not None:
            return _orchestrator

        # get_session_store() uses a separate lock — safe to call here.
        store = get_session_store()

        from config import Config
        import events

        def _sync_legacy(event: str, payload: dict) -> None:
            if event == "pipeline.state":
                name = payload.get("state") or payload.get("pipeline_state") or "IDLE"
                events.set_pipeline_state(str(name))

        _bus.subscribe(_sync_legacy)
        import pipeline

        _orchestrator = Orchestrator(
            bus=_bus,
            process_query=_default_process_query,
            speak=_default_speak,
            config_loader=Config.load,
            interrupt_event=pipeline._interrupt,
            request_interrupt=pipeline.request_interrupt,
            clear_interrupt=pipeline._clear_interrupt,
            session_store=store,
        )
        return _orchestrator


def reset_for_tests() -> None:
    """Tear down all singletons so the next call builds fresh."""
    global _orchestrator, _session_store, _lane_manager
    with _orc_lock:
        if _orchestrator is not None:
            _orchestrator.shutdown()
        _orchestrator = None
    with _store_lock:
        _session_store = None
    with _lane_lock:
        if _lane_manager is not None:
            try:
                _lane_manager.background.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        _lane_manager = None
