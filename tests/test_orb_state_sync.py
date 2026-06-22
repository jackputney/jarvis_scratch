"""Orb state sync — single source of truth via events bus."""

from __future__ import annotations

import sys
import time

import pytest

pytest.importorskip("PyQt6")

import events
from ui.face import FaceWidget, JarvisState


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app
    app.processEvents()


@pytest.fixture
def face_widget(qapp):
    widget = FaceWidget()
    widget.connect_pipeline_state()
    yield widget
    widget.shutdown()
    qapp.processEvents()


def test_orb_tracks_pipeline_state_after_rapid_transitions(face_widget, qapp):
    """100 rapid transitions — orb must match pipeline state after debounce."""
    sequence = [
        "IDLE",
        "LISTENING",
        "THINKING",
        "SPEAKING",
        "FOLLOWUP_WINDOW",
        "IDLE",
    ]
    for _ in range(100):
        for name in sequence:
            events.set_pipeline_state(name)
    qapp.processEvents()
    time.sleep(0.08)
    qapp.processEvents()

    assert events.get_pipeline_state() == "IDLE"
    assert face_widget._authoritative_state == "IDLE"
    assert face_widget._orb._animator.state == "IDLE"


def test_all_jarvis_states_reachable_via_events(face_widget, qapp):
    for state in JarvisState:
        events.set_pipeline_state(state.name)
    qapp.processEvents()
    time.sleep(0.08)
    qapp.processEvents()
    assert face_widget._orb._animator.state == JarvisState.FOLLOWUP_WINDOW.name
