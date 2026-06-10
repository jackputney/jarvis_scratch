"""
ui/face.py — PyQt6 floating orb face widget for Jarvis.

A 300x300 frameless, always-on-top, transparent window lives in the top-right
corner.  A single animated orb (deep sky blue, #00BFFF) reflects the pipeline
state:

  IDLE      — static orb, no animation
  LISTENING — slow breathing pulse (scale 0.9→1.1 over 1.5 s)
  THINKING  — fast clockwise rotating arc around the orb
  SPEAKING  — amplitude ripple rings expanding outward from the centre

State changes come from the pipeline thread via set_state(), which is safe to
call from any thread — it posts to the Qt event loop via QMetaObject.invokeMethod.

Clicking the orb toggles the global mute flag exposed as FaceWidget.muted.
"""

from __future__ import annotations

import math
from enum import Enum, auto

from PyQt6.QtCore import (
    Q_ARG,
    QMetaObject,
    QPointF,
    Qt,
    QTimer,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QWidget


class JarvisState(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()


# ---------------------------------------------------------------------------
# Orb widget
# ---------------------------------------------------------------------------

class OrbWidget(QWidget):
    """The animated orb canvas. Drawn entirely in paintEvent."""

    ORB_COLOUR = QColor("#00BFFF")
    WARN_COLOUR = QColor("#FFB000")   # amber — daily spend ≥ 80%
    CAPPED_COLOUR = QColor("#FF3B30")  # red — daily budget reached
    MUTED_COLOUR = QColor("#888888")
    GLOW_COLOUR = QColor(0, 191, 255, 60)
    ARC_COLOUR = QColor("#00BFFF")
    RING_COLOUR = QColor(0, 191, 255, 120)
    BG_COLOUR = QColor(0, 0, 0, 0)

    def _base_colour(self) -> QColor:
        """Pick the orb colour by priority: capped > warn > muted > normal."""
        if self.budget_level == "capped":
            return self.CAPPED_COLOUR
        if self.budget_level == "warn":
            return self.WARN_COLOUR
        if self.muted:
            return self.MUTED_COLOUR
        return self.ORB_COLOUR

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state: JarvisState = JarvisState.IDLE
        self.muted: bool = False
        # Budget level drives the orb colour: 'normal' (blue), 'warn' (amber),
        # 'capped' (red). Set from the pipeline via FaceWidget.set_budget_level.
        self.budget_level: str = "normal"

        self._tick: int = 0  # animation frame counter
        self._rings: list[float] = []  # ring radii for SPEAKING ripple

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(16)  # ~60 fps

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

    def _on_tick(self) -> None:
        self._tick += 1

        if self.state == JarvisState.SPEAKING:
            # Spawn a new ring every ~20 frames
            if self._tick % 20 == 0:
                self._rings.append(0.0)
            # Expand and expire rings
            self._rings = [r + 2.5 for r in self._rings if r < 120]

        self.update()

    def set_state(self, state: JarvisState) -> None:
        self.state = state
        if state != JarvisState.SPEAKING:
            self._rings.clear()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        cx, cy = self.width() / 2, self.height() / 2
        r = min(self.width(), self.height()) * 0.35
        dx = event.position().x() - cx
        dy = event.position().y() - cy
        if dx * dx + dy * dy <= r * r:
            # Click landed on the orb → toggle mute and consume the event.
            self.muted = not self.muted
            self.update()
        else:
            # Outside the orb → let the parent FaceWidget handle it so the
            # window can be dragged (F9).
            event.ignore()

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.BG_COLOUR)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        base_r = min(w, h) * 0.30  # base orb radius (30% of smallest dimension)

        # ----- State-specific modifiers ----------------------------------------

        scale = 1.0
        arc_angle: float | None = None

        if self.state == JarvisState.LISTENING:
            # Breathing: sinusoidal scale between 0.9 and 1.1, period ~90 frames
            scale = 1.0 + 0.1 * math.sin(self._tick * (2 * math.pi / 90))

        elif self.state == JarvisState.THINKING:
            # Rotating arc — we'll draw it after the orb
            arc_angle = (self._tick * 4) % 360  # 4° per frame

        elif self.state == JarvisState.SPEAKING:
            # Gentle pulse on the orb itself
            scale = 1.0 + 0.05 * math.sin(self._tick * (2 * math.pi / 20))

        r = base_r * scale

        # ----- Glow halo -------------------------------------------------------
        glow_gradient = QRadialGradient(QPointF(cx, cy), r * 1.8)
        glow_gradient.setColorAt(0.0, QColor(0, 191, 255, 80))
        glow_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow_gradient))
        painter.drawEllipse(QPointF(cx, cy), r * 1.8, r * 1.8)

        # ----- Orb body --------------------------------------------------------
        orb_gradient = QRadialGradient(QPointF(cx - r * 0.25, cy - r * 0.25), r * 1.2)
        orb_colour = self._base_colour()
        orb_gradient.setColorAt(0.0, orb_colour.lighter(160))
        orb_gradient.setColorAt(1.0, orb_colour.darker(130))
        painter.setBrush(QBrush(orb_gradient))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # ----- THINKING: rotating arc ------------------------------------------
        if arc_angle is not None:
            pen = QPen(self.ARC_COLOUR)
            pen.setWidth(3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc_r = r + 14
            rect_x = cx - arc_r
            rect_y = cy - arc_r
            rect_size = arc_r * 2
            # drawArc uses 1/16th-degree units; sweep 120°
            start_angle = int((90 - arc_angle) * 16)
            sweep_angle = int(120 * 16)
            painter.drawArc(
                int(rect_x), int(rect_y), int(rect_size), int(rect_size),
                start_angle, sweep_angle,
            )

        # ----- SPEAKING: ripple rings ------------------------------------------
        if self.state == JarvisState.SPEAKING:
            for ring_r in self._rings:
                alpha = max(0, int(120 * (1 - ring_r / 120)))
                ring_pen = QPen(QColor(0, 191, 255, alpha))
                ring_pen.setWidth(2)
                painter.setPen(ring_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), ring_r + r, ring_r + r)

        painter.end()


# ---------------------------------------------------------------------------
# Face window
# ---------------------------------------------------------------------------

class FaceWidget(QWidget):
    """Frameless, always-on-top host window for the orb."""

    def __init__(self) -> None:
        super().__init__()
        # NOTE: deliberately NOT using Qt.Tool here. On macOS a Tool window is an
        # accessory palette that is hidden whenever its app isn't frontmost — so
        # while you're typing in the terminal the orb would vanish. Frameless +
        # WindowStaysOnTopHint keeps it visible above everything regardless of
        # which app has focus.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Show without stealing focus from whatever the user is doing.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(300, 300)
        self.setWindowTitle("Jarvis")

        self._orb = OrbWidget(self)
        self._orb.setGeometry(0, 0, 300, 300)

        # Position in top-right of the primary screen
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            self.move(geom.right() - 320, geom.top() + 20)

        # Dragging support
        self._drag_pos: QPointF | None = None

    def show_overlay(self) -> None:
        """Show the orb and lift it above other windows (call from main thread)."""
        self.show()
        self.raise_()

    # ---- Thread-safe state update -------------------------------------------

    @pyqtSlot(str)
    def _apply_state(self, state_name: str) -> None:
        try:
            state = JarvisState[state_name]
        except KeyError:
            return
        self._orb.set_state(state)

    def set_state(self, state: JarvisState) -> None:
        """Safe to call from any thread. Posts to the Qt event loop.

        The state name must be wrapped in Q_ARG — PyQt6's invokeMethod does not
        auto-convert bare Python objects to the QGenericArgument the C++ slot
        expects, and passing a raw str raises TypeError.
        """
        QMetaObject.invokeMethod(
            self,
            "_apply_state",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, state.name),
        )

    @pyqtSlot(str)
    def _apply_budget_level(self, level: str) -> None:
        self._orb.budget_level = level
        self._orb.update()

    def set_budget_level(self, level: str) -> None:
        """Safe to call from any thread. 'normal' | 'warn' | 'capped'."""
        QMetaObject.invokeMethod(
            self,
            "_apply_budget_level",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, level),
        )

    @property
    def muted(self) -> bool:
        return self._orb.muted

    # ---- Drag-to-move -------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition() - QPointF(self.pos())

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition() - self._drag_pos
            self.move(int(new_pos.x()), int(new_pos.y()))

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001
        self._drag_pos = None
