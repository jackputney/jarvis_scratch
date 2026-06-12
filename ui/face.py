"""
ui/face.py — PyQt6 popup face window for Jarvis.

A always-on-top popup panel (dark rounded box matching the dashboard theme)
shows the animated orb plus a live status label. The orb reflects pipeline
state:

  IDLE      — static orb
  LISTENING — slow breathing pulse
  THINKING  — fast clockwise rotating arc
  SPEAKING  — amplitude ripple rings

State changes come from the pipeline thread via set_state(), which is safe to
call from any thread — it posts to the Qt event loop via QMetaObject.invokeMethod.

Click the orb to toggle mute. Drag anywhere on the panel chrome to reposition.
Use the Stop button or Escape to interrupt Jarvis mid-response.
"""

from __future__ import annotations

import math
from enum import Enum, auto

from collections.abc import Callable

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
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QRadialGradient,
    QShortcut,
)
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

# Match the dashboard palette.
PANEL_BG = QColor("#0a0e14")
PANEL_BORDER = QColor("#00BFFF")
PANEL_INNER = QColor("#111722")
TEXT_COLOUR = QColor("#d7e0ea")
MUTED_TEXT = QColor("#7c8a9a")
ACCENT = QColor("#00BFFF")

PANEL_W = 320
PANEL_H = 440
ORB_SIZE = 260
CORNER_RADIUS = 16


class JarvisState(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()


_STATE_LABELS = {
    JarvisState.IDLE: "Ready",
    JarvisState.LISTENING: "Listening…",
    JarvisState.THINKING: "Thinking…",
    JarvisState.SPEAKING: "Speaking…",
}


# ---------------------------------------------------------------------------
# Orb widget
# ---------------------------------------------------------------------------

class OrbWidget(QWidget):
    """The animated orb canvas. Drawn entirely in paintEvent."""

    ORB_COLOUR = QColor("#00BFFF")
    WARN_COLOUR = QColor("#FFB000")
    CAPPED_COLOUR = QColor("#FF3B30")
    MUTED_COLOUR = QColor("#888888")
    ARC_COLOUR = QColor("#00BFFF")
    BG_COLOUR = QColor(0, 0, 0, 0)

    def _base_colour(self) -> QColor:
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
        self.budget_level: str = "normal"

        self._tick: int = 0
        self._rings: list[float] = []

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(16)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _on_tick(self) -> None:
        self._tick += 1
        if self.state == JarvisState.SPEAKING:
            if self._tick % 20 == 0:
                self._rings.append(0.0)
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
            self.muted = not self.muted
            self.update()
            face = self.parent()
            if face is not None and hasattr(face, "_refresh_status_label"):
                face._refresh_status_label()
        else:
            event.ignore()

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.BG_COLOUR)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        base_r = min(w, h) * 0.30

        scale = 1.0
        arc_angle: float | None = None

        if self.state == JarvisState.LISTENING:
            scale = 1.0 + 0.1 * math.sin(self._tick * (2 * math.pi / 90))
        elif self.state == JarvisState.THINKING:
            arc_angle = (self._tick * 4) % 360
        elif self.state == JarvisState.SPEAKING:
            scale = 1.0 + 0.05 * math.sin(self._tick * (2 * math.pi / 20))

        r = base_r * scale

        glow_gradient = QRadialGradient(QPointF(cx, cy), r * 1.8)
        glow_gradient.setColorAt(0.0, QColor(0, 191, 255, 80))
        glow_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow_gradient))
        painter.drawEllipse(QPointF(cx, cy), r * 1.8, r * 1.8)

        orb_gradient = QRadialGradient(QPointF(cx - r * 0.25, cy - r * 0.25), r * 1.2)
        orb_colour = self._base_colour()
        orb_gradient.setColorAt(0.0, orb_colour.lighter(160))
        orb_gradient.setColorAt(1.0, orb_colour.darker(130))
        painter.setBrush(QBrush(orb_gradient))
        painter.drawEllipse(QPointF(cx, cy), r, r)

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
            start_angle = int((90 - arc_angle) * 16)
            sweep_angle = int(120 * 16)
            painter.drawArc(
                int(rect_x), int(rect_y), int(rect_size), int(rect_size),
                start_angle, sweep_angle,
            )

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
# Popup face window
# ---------------------------------------------------------------------------

class FaceWidget(QWidget):
    """Always-on-top popup panel with the Jarvis orb and status readout."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Window,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(PANEL_W, PANEL_H)
        self.setWindowTitle("Jarvis")

        self._drag_pos: QPointF | None = None
        self._current_state = JarvisState.IDLE
        self._interrupt_cb: Callable[[], None] | None = None

        # --- Layout (labels sit on top of the painted panel) ----------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(6)

        self._title = QLabel("JARVIS")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        self._title.setFont(title_font)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(f"color: {ACCENT.name()}; background: transparent;")

        self._orb = OrbWidget(self)
        self._orb.setFixedSize(ORB_SIZE, ORB_SIZE)

        self._status = QLabel(_STATE_LABELS[JarvisState.IDLE])
        status_font = QFont()
        status_font.setPointSize(11)
        self._status.setFont(status_font)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color: {TEXT_COLOUR.name()}; background: transparent;")

        self._hint = QLabel("Click orb to mute · Stop button or Esc to interrupt")
        hint_font = QFont()
        hint_font.setPointSize(9)
        self._hint.setFont(hint_font)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet(f"color: {MUTED_TEXT.name()}; background: transparent;")

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setFixedHeight(34)
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setStyleSheet(
            "QPushButton {"
            f"  background-color: #2a1214;"
            f"  color: #ff6b6b;"
            f"  border: 1px solid #ff3b30;"
            "  border-radius: 8px;"
            "  font-weight: 600;"
            "  padding: 4px 12px;"
            "}"
            "QPushButton:hover { background-color: #3d1818; }"
            "QPushButton:pressed { background-color: #1a0a0a; }"
        )
        self._stop_btn.clicked.connect(self._on_stop)

        layout.addWidget(self._title)
        layout.addWidget(self._orb, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)
        layout.addWidget(self._stop_btn)
        layout.addWidget(self._hint)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._on_stop)

        # Top-right of the primary screen, offset so it feels like a popup.
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            self.move(geom.right() - PANEL_W - 24, geom.top() + 48)

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        """Draw the rounded dark panel + accent border behind the widgets."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)

        # Soft outer glow.
        glow_pen = QPen(QColor(0, 191, 255, 40))
        glow_pen.setWidth(6)
        painter.setPen(glow_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, CORNER_RADIUS + 2, CORNER_RADIUS + 2)

        # Panel fill.
        painter.setPen(QPen(PANEL_BORDER, 1.5))
        painter.setBrush(QBrush(PANEL_BG))
        painter.drawRoundedRect(rect, CORNER_RADIUS, CORNER_RADIUS)

        # Inner inset for depth.
        inner = rect.adjusted(8, 8, -8, -8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(PANEL_INNER))
        painter.drawRoundedRect(inner, CORNER_RADIUS - 4, CORNER_RADIUS - 4)

        painter.end()

    def set_interrupt_callback(self, callback: Callable[[], None]) -> None:
        """Wire the Stop button / Escape key to pipeline.request_interrupt()."""
        self._interrupt_cb = callback

    def _on_stop(self) -> None:
        if self._interrupt_cb:
            self._interrupt_cb()
        self._status.setText("Stopped")

    def show_overlay(self) -> None:
        """Show the popup and lift it above other windows (call from main thread)."""
        self.show()
        self.raise_()
        self.activateWindow()

    @pyqtSlot(str)
    def _apply_state(self, state_name: str) -> None:
        try:
            state = JarvisState[state_name]
        except KeyError:
            return
        self._current_state = state
        self._orb.set_state(state)
        self._refresh_status_label()

    def set_state(self, state: JarvisState) -> None:
        """Safe to call from any thread."""
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

    def _refresh_status_label(self) -> None:
        label = _STATE_LABELS.get(self._current_state, self._current_state.name.title())
        if self._orb.muted:
            label = f"{label}  (muted)"
        self._status.setText(label)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition() - QPointF(self.pos())

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition() - self._drag_pos
            self.move(int(new_pos.x()), int(new_pos.y()))

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001
        self._drag_pos = None
