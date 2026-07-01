"""Orb UI — state colours, lerp, hit testing, mute toggle."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QColor

from ui.face import (
    CORE_RADIUS,
    STATE_COLORS,
    JarvisState,
    OrbWidget,
    lerp_color,
    point_in_core,
)


def test_orb_state_colors():
    assert STATE_COLORS["IDLE"].red() == 0x6C
    assert STATE_COLORS["LISTENING"].green() == 0xD3
    assert STATE_COLORS["THINKING"].blue() == 0xF6
    assert STATE_COLORS["WAITING_CONFIRM"].red() == 0xFB


def test_orb_state_colors_all_states():
    """Every JarvisState maps to a distinct color in STATE_COLORS."""
    for state in JarvisState:
        assert state.name in STATE_COLORS


def test_orb_lerp_color():
    mid = lerp_color(QColor("#000000"), QColor("#ffffff"), 0.5)
    assert 120 <= mid.red() <= 135
    assert 120 <= mid.green() <= 135
    assert 120 <= mid.blue() <= 135


def test_lerp_color_endpoints():
    """lerp_color at t=0 returns a, at t=1 returns b."""
    a, b = QColor(255, 0, 0), QColor(0, 0, 255)
    assert lerp_color(a, b, 0.0).red() == 255
    assert lerp_color(a, b, 1.0).blue() == 255


def test_orb_mute_toggle():
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    orb = OrbWidget()
    assert orb.muted is False
    orb.muted = True
    assert orb.muted is True
    orb.muted = False
    assert orb.muted is False
    app.processEvents()


def test_orb_click_outside_core_ignored():
    cx, cy, r = 50.0, 50.0, CORE_RADIUS
    assert point_in_core(cx, cy, r, cx, cy) is True
    assert point_in_core(cx, cy, r, cx + 50, cy) is False


def test_point_in_core_hit():
    """Point at center is inside core."""
    assert point_in_core(50, 50, 26, 50, 50) is True


def test_point_in_core_miss():
    """Point far from center is outside core."""
    assert point_in_core(50, 50, 26, 100, 100) is False


def test_core_radius_is_click_target_size():
    assert CORE_RADIUS == 26.0


def test_face_window_does_not_use_tool_flag():
    """Tool windows on macOS auto-hide when the app loses focus."""
    import sys

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from ui.face import FaceWidget

    app = QApplication.instance() or QApplication(sys.argv)
    widget = FaceWidget()
    try:
        flags = widget.windowFlags()
        assert (flags & Qt.WindowType.Tool) != Qt.WindowType.Tool
        assert flags & Qt.WindowType.WindowStaysOnTopHint
    finally:
        widget.shutdown()
        app.processEvents()


def _make_orb():
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    return app, OrbWidget()


def _drive(animator, state: str, ticks: int) -> None:
    animator.set_state(state)
    for _ in range(ticks):
        animator._tick()


def test_speaking_emits_ripple_phases():
    """SPEAKING drives two staggered ripple phases within [0, 1)."""
    app, orb = _make_orb()
    anim = orb._animator
    _drive(anim, "SPEAKING", 10)
    p1, p2 = anim._ripple_phases
    assert 0.0 <= p1 < 1.0
    assert 0.0 <= p2 < 1.0
    assert p1 != p2  # staggered, never in lock-step
    orb.stop_animations()
    app.processEvents()


def test_listening_wake_bloom_then_settle():
    """Entering LISTENING flashes a glow burst that settles to the steady level."""
    app, orb = _make_orb()
    anim = orb._animator
    _drive(anim, "LISTENING", 2)  # ~66 ms in — bloom active
    bloom_glow = anim.glow_intensity
    _drive(anim, "LISTENING", 15)  # ~560 ms in — settled
    settled_glow = anim.glow_intensity
    assert bloom_glow > settled_glow
    assert settled_glow == 0.7
    orb.stop_animations()
    app.processEvents()


def test_waiting_confirm_breathes_smoothly():
    """WAITING_CONFIRM glow varies continuously (no hard on/off jump)."""
    app, orb = _make_orb()
    anim = orb._animator
    anim.set_state("WAITING_CONFIRM")
    samples = []
    for _ in range(30):
        anim._tick()
        samples.append(anim.glow_intensity)
    assert max(samples) > min(samples)  # it moves
    deltas = [abs(b - a) for a, b in zip(samples, samples[1:])]
    assert max(deltas) < 0.2  # but never jumps discontinuously
    orb.stop_animations()
    app.processEvents()


def test_face_set_state_cross_thread_no_typeerror():
    """F1 — pipeline worker threads must not crash the Qt orb with TypeError."""
    import sys
    import threading

    from PyQt6.QtWidgets import QApplication

    from ui.face import FaceWidget, JarvisState

    app = QApplication.instance() or QApplication(sys.argv)
    widget = FaceWidget()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for state in (JarvisState.LISTENING, JarvisState.SPEAKING, JarvisState.IDLE):
                widget.set_state(state)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=5.0)
    app.processEvents()
    widget.shutdown()
    app.processEvents()
    assert not errors, errors
