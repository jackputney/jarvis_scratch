"""
ui/face.py — PyQt6 premium floating orb HUD for Jarvis.

Landscape frosted-glass panel with an 8-layer luminous sphere, state-driven
animation, and thread-safe set_state() from the pipeline.
Click the orb to toggle mute; drag the panel to reposition; Escape cancels.
"""

from __future__ import annotations

import logging
import math
import os
import platform
from collections.abc import Callable
from enum import Enum, auto

from PyQt6.QtCore import (
    Q_ARG,
    QMetaObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QShortcut,
)
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger("jarvis.ui")

# Landscape HUD — frosted panel with orb left, state label right
HUD_W = 200
HUD_H = 120
PANEL_W = 180.0
PANEL_H = 100.0
PANEL_RADIUS = 20.0
PANEL_MARGIN_X = (HUD_W - PANEL_W) / 2.0
PANEL_MARGIN_Y = (HUD_H - PANEL_H) / 2.0
CORE_RADIUS = 26.0  # 52 px diameter sphere

# Orb sits left-centre inside the panel
ORB_CX = PANEL_MARGIN_X + 16.0 + CORE_RADIUS
ORB_CY = PANEL_MARGIN_Y + PANEL_H / 2.0

# Back-compat alias used by tests / callers
HUD_SIZE = HUD_W

STATE_COLORS: dict[str, QColor] = {
    "IDLE": QColor("#6C7BF7"),
    "LISTENING": QColor("#34D399"),
    "THINKING": QColor("#8B5CF6"),
    "SPEAKING": QColor("#6C7BF7"),
    "WAITING_CONFIRM": QColor("#FBBF24"),
    "ERROR": QColor("#F87171"),
}

_STATE_LABELS: dict[str, tuple[str, str]] = {
    "IDLE": ("Jarvis", ""),
    "LISTENING": ("Listening...", ""),
    "THINKING": ("Thinking...", ""),
    "SPEAKING": ("Speaking...", ""),
    "WAITING_CONFIRM": ("Needs approval", "Check dashboard"),
    "ERROR": ("Error", ""),
}

_STATE_TOOLTIPS = {
    "IDLE": "Jarvis — idle",
    "LISTENING": "Jarvis — listening...",
    "THINKING": "Jarvis — thinking...",
    "SPEAKING": "Jarvis — speaking...",
    "WAITING_CONFIRM": "Jarvis — awaiting approval",
    "ERROR": "Jarvis — error",
}


def lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    """Linear RGBA interpolation between two colours."""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def point_in_core(cx: float, cy: float, core_radius: float, x: float, y: float) -> bool:
    """Return True when (x, y) lies inside the orb sphere."""
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= core_radius * core_radius


def _panel_rect() -> QRectF:
    return QRectF(PANEL_MARGIN_X, PANEL_MARGIN_Y, PANEL_W, PANEL_H)


def _try_macos_vibrancy(widget: QWidget) -> bool:
    """Attach native macOS frosted vibrancy when pyobjc is available."""
    if platform.system() != "Darwin":
        return False
    # AppKit vibrancy needs a real window; offscreen Qt (pytest/CI) segfaults here.
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False
    try:
        from ctypes import c_void_p  # noqa: PLC0415

        import objc  # noqa: PLC0415
        from AppKit import (  # noqa: PLC0415
            NSVisualEffectBlendingModeBehindWindow,
            NSVisualEffectMaterialHUDWindow,
            NSVisualEffectStateActive,
            NSVisualEffectView,
        )

        view = NSVisualEffectView.alloc().init()
        view.setMaterial_(NSVisualEffectMaterialHUDWindow)
        view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        view.setState_(NSVisualEffectStateActive)
        view.setWantsLayer_(True)

        win_id = int(widget.winId())
        ns_view = objc.objc_object(c_void_p=win_id)
        if ns_view is not None:
            ns_view.addSubview_(view)
            return True
    except Exception:
        return False
    return False


class JarvisState(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    WAITING_CONFIRM = auto()
    SPEAKING = auto()


class OrbAnimator:
    """Drives sphere visual parameters from pipeline state at ~30 fps."""

    def __init__(self, widget: "OrbWidget") -> None:
        self._widget = widget
        self._state = "IDLE"
        self._t = 0
        self._core_radius = CORE_RADIUS
        self._target_core_radius = CORE_RADIUS
        self._arc_angle = 0.0
        self._color = QColor(STATE_COLORS["IDLE"])
        self._target_color = QColor(STATE_COLORS["IDLE"])
        self._budget_level = "normal"
        self._error_flash_until = 0
        self._state_enter_t = 0

        self.glow_intensity = 0.3
        self.glow_extent = 8.0
        self.specular_alpha = 200
        self._sonar_phase = 0.0
        self._sonar_radius = 0.0

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    @property
    def state(self) -> str:
        return self._state

    @property
    def core_radius(self) -> float:
        return self._core_radius

    @property
    def color(self) -> QColor:
        return self._color

    @property
    def arc_angle(self) -> float:
        return self._arc_angle

    def set_budget_level(self, level: str) -> None:
        self._budget_level = level

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state_enter_t = self._t
        self._state = state
        if state == "ERROR":
            self._error_flash_until = self._t + 400
        self._target_color = STATE_COLORS.get(state, STATE_COLORS["IDLE"])
        if self._budget_level == "capped":
            self._target_color = STATE_COLORS["ERROR"]
        elif self._budget_level == "warn" and state == "IDLE":
            self._target_color = STATE_COLORS["WAITING_CONFIRM"]
        if state == "LISTENING":
            self._target_core_radius = CORE_RADIUS + 2.0

    def _tick(self) -> None:
        self._t += 33
        self._color = lerp_color(self._color, self._target_color, 0.15)
        handler = getattr(self, f"_anim_{self._state.lower()}", self._anim_idle)
        handler()
        if self._t < self._error_flash_until:
            self._color = lerp_color(self._color, STATE_COLORS["ERROR"], 0.45)
        self._widget.update()

    def _lerp_core_toward_target(self, speed: float = 0.18) -> None:
        self._core_radius += (self._target_core_radius - self._core_radius) * speed

    def _anim_idle(self) -> None:
        t = self._t
        self.glow_intensity = 0.3 + 0.15 * math.sin(t * 2 * math.pi / 4000)
        self.glow_extent = 8.0
        self.specular_alpha = 200
        self._target_core_radius = CORE_RADIUS
        self._lerp_core_toward_target()

    def _anim_listening(self) -> None:
        self.glow_intensity = 0.7
        self.glow_extent = 8.0
        self.specular_alpha = 240
        elapsed = self._t - self._state_enter_t
        if elapsed < 200:
            frac = elapsed / 200.0
            self._target_core_radius = CORE_RADIUS + 2.0 * frac
        else:
            self._target_core_radius = CORE_RADIUS + 2.0
        self._lerp_core_toward_target(0.25)
        # Sonar ping — one ring every 800 ms
        cycle = (self._t - self._state_enter_t) % 800
        self._sonar_phase = cycle / 800.0
        self._sonar_radius = CORE_RADIUS + 10.0 + self._sonar_phase * 10.0

    def _anim_thinking(self) -> None:
        self._arc_angle = (self._arc_angle + 5.0) % 360
        self.glow_intensity = 0.5
        self.glow_extent = 8.0
        self.specular_alpha = 200
        self._target_core_radius = CORE_RADIUS
        self._lerp_core_toward_target()

    def _anim_speaking(self) -> None:
        t = self._t
        pulse = math.sin(t * 2 * math.pi / 600)
        self.glow_intensity = 0.4 + 0.3 * pulse
        self.glow_extent = 8.0 + 4.0 * (0.5 + 0.5 * pulse)
        self.specular_alpha = 150 + 70 * (0.5 + 0.5 * pulse)
        self._core_radius = CORE_RADIUS + 1.5 * pulse

    def _anim_waiting_confirm(self) -> None:
        cycle = self._t % 2000
        on_phase = cycle < 1500
        self.glow_intensity = 0.8 if on_phase else 0.15
        self.glow_extent = 8.0
        self.specular_alpha = 200
        self._target_core_radius = CORE_RADIUS
        self._lerp_core_toward_target()

    def _anim_error(self) -> None:
        self._anim_idle()


class OrbWidget(QWidget):
    """Frosted panel + 8-layer luminous sphere."""

    mute_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.muted = False
        self._animator = OrbAnimator(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(HUD_W, HUD_H)
        self._panel_rect = _panel_rect()
        self._update_tooltip()

    @property
    def panel_rect(self) -> QRectF:
        return self._panel_rect

    @property
    def orb_center(self) -> tuple[float, float]:
        return ORB_CX, ORB_CY

    def set_state(self, state: JarvisState) -> None:
        self._animator.set_state(state.name)
        self._update_tooltip()

    def set_budget_level(self, level: str) -> None:
        self._animator.set_budget_level(level)
        self._animator.set_state(self._animator.state)

    def _update_tooltip(self) -> None:
        label = _STATE_TOOLTIPS.get(self._animator.state, "Jarvis")
        if self.muted:
            label += " (muted)"
        self.setToolTip(label)

    def _alpha_scale(self) -> float:
        return 0.5 if self.muted else 1.0

    def _toggle_mute(self) -> None:
        self.muted = not self.muted
        self.mute_toggled.emit(self.muted)
        self._update_tooltip()
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        pos = event.position()
        cx, cy = ORB_CX, ORB_CY
        if point_in_core(cx, cy, self._animator.core_radius, pos.x(), pos.y()):
            self._toggle_mute()
            event.accept()
            return
        if self._panel_rect.contains(pos):
            parent = self.parent()
            if isinstance(parent, FaceWidget):
                parent.start_drag(event)
            event.accept()
            return
        event.ignore()

    @staticmethod
    def _paint_frosted_panel(painter: QPainter, rect: QRectF) -> None:
        """Cross-platform frosted glass simulation."""
        path = QPainterPath()
        path.addRoundedRect(rect, PANEL_RADIUS, PANEL_RADIUS)

        painter.setBrush(QColor(15, 18, 28, 180))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)

        inner_grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        inner_grad.setColorAt(0.0, QColor(255, 255, 255, 8))
        inner_grad.setColorAt(0.5, QColor(255, 255, 255, 0))
        inner_grad.setColorAt(1.0, QColor(0, 0, 0, 15))
        painter.setBrush(QBrush(inner_grad))
        painter.drawPath(path)

        highlight_pen = QPen(QColor(255, 255, 255, 25), 0.5)
        painter.setPen(highlight_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        highlight_path = QPainterPath()
        highlight_path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), PANEL_RADIUS, PANEL_RADIUS)
        painter.drawPath(highlight_path)

        border_pen = QPen(QColor(255, 255, 255, 18), 1.0)
        painter.setPen(border_pen)
        painter.drawPath(highlight_path)

    def _paint_sphere(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        orb_r: float,
        anim: OrbAnimator,
    ) -> None:
        c = anim.color
        scale = self._alpha_scale()
        glow_r = orb_r + anim.glow_extent
        gi = anim.glow_intensity * scale

        # Layer 1 — drop shadow
        shadow_grad = QRadialGradient(cx, cy + 4, orb_r * 1.1)
        shadow_grad.setColorAt(0.0, QColor(0, 0, 0, int(60 * scale)))
        shadow_grad.setColorAt(0.7, QColor(0, 0, 0, int(20 * scale)))
        shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(shadow_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy + 4), orb_r * 1.1, orb_r * 0.7)

        # Listening sonar ping
        if anim.state == "LISTENING" and anim._sonar_phase < 1.0:
            ping_alpha = int(80 * (1.0 - anim._sonar_phase) * scale)
            ping_pen = QPen(QColor(c.red(), c.green(), c.blue(), ping_alpha), 1.0)
            painter.setPen(ping_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), anim._sonar_radius, anim._sonar_radius)

        # Layer 2 — ambient glow
        glow_grad = QRadialGradient(cx, cy, glow_r)
        glow_grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), int(gi * 80)))
        glow_grad.setColorAt(0.5, QColor(c.red(), c.green(), c.blue(), int(gi * 30)))
        glow_grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        painter.setBrush(QBrush(glow_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        # THINKING orbital arcs (outside sphere)
        if anim.state == "THINKING":
            arc_rect = QRectF(
                cx - orb_r - 6,
                cy - orb_r - 6,
                (orb_r + 6) * 2,
                (orb_r + 6) * 2,
            )
            pen = QPen(QColor(c.red(), c.green(), c.blue(), int(180 * scale * 0.7)), 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(arc_rect, int(anim.arc_angle * 16), 90 * 16)
            pen2 = QPen(QColor(c.red(), c.green(), c.blue(), int(100 * scale * 0.4)), 1.5)
            pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen2)
            painter.drawArc(arc_rect, int(-anim.arc_angle * 0.7 * 16), 60 * 16)

        # Clip subsequent sphere layers to the orb circle
        clip_path = QPainterPath()
        clip_path.addEllipse(QPointF(cx, cy), orb_r, orb_r)
        painter.save()
        painter.setClipPath(clip_path)

        # Layer 3 — base sphere
        light_x = -orb_r * 0.3
        light_y = -orb_r * 0.3
        base_grad = QRadialGradient(cx + light_x, cy + light_y, orb_r * 1.2)
        base_grad.setColorAt(0.0, c.lighter(170))
        base_grad.setColorAt(0.25, c.lighter(130))
        base_grad.setColorAt(0.55, c)
        base_grad.setColorAt(0.85, c.darker(140))
        base_grad.setColorAt(1.0, c.darker(170))
        painter.setBrush(QBrush(base_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), orb_r, orb_r)

        # Layer 4 — sub-surface scattering
        sss_grad = QRadialGradient(cx + orb_r * 0.3, cy + orb_r * 0.2, orb_r * 0.6)
        lit = c.lighter(150)
        sss_grad.setColorAt(0.0, QColor(lit.red(), lit.green(), lit.blue(), int(40 * scale)))
        sss_grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        painter.setBrush(QBrush(sss_grad))
        painter.drawEllipse(QPointF(cx, cy), orb_r, orb_r)

        painter.restore()

        # Layer 5 — primary specular (on top, not clipped)
        spec_x = cx - orb_r * 0.28
        spec_y = cy - orb_r * 0.28
        spec_r = orb_r * 0.22
        sa = int(anim.specular_alpha * scale)
        spec_grad = QRadialGradient(spec_x, spec_y, spec_r)
        spec_grad.setColorAt(0.0, QColor(255, 255, 255, sa))
        spec_grad.setColorAt(0.3, QColor(255, 255, 255, int(sa * 0.5)))
        spec_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(spec_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(spec_x, spec_y), spec_r, spec_r)

        # Layer 6 — secondary specular
        spec2_x = cx + orb_r * 0.2
        spec2_y = cy + orb_r * 0.25
        spec2_r = orb_r * 0.12
        spec2_grad = QRadialGradient(spec2_x, spec2_y, spec2_r)
        spec2_grad.setColorAt(0.0, QColor(255, 255, 255, int(50 * scale)))
        spec2_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(spec2_grad))
        painter.drawEllipse(QPointF(spec2_x, spec2_y), spec2_r, spec2_r)

        # Layer 7 — rim light (Fresnel)
        rim_color = c.lighter(160)
        rim_pen = QPen(
            QColor(rim_color.red(), rim_color.green(), rim_color.blue(), int(50 * scale)),
            1.5,
        )
        painter.setPen(rim_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), orb_r - 0.5, orb_r - 0.5)
        bright_rim = QPen(
            QColor(rim_color.red(), rim_color.green(), rim_color.blue(), int(90 * scale)),
            1.5,
        )
        bright_rim.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(bright_rim)
        arc_rect = QRectF(cx - orb_r + 1, cy - orb_r + 1, (orb_r - 1) * 2, (orb_r - 1) * 2)
        painter.drawArc(arc_rect, -60 * 16, 120 * 16)

        # Layer 8 — inner depth ring
        inner_ring_r = orb_r * 0.6
        inner_ring_pen = QPen(QColor(255, 255, 255, int(15 * scale)), 0.5)
        painter.setPen(inner_ring_pen)
        painter.drawEllipse(QPointF(cx - 2, cy - 2), inner_ring_r, inner_ring_r)

    def _paint_state_label(self, painter: QPainter, cx: float, cy: float, orb_r: float, state: str) -> None:
        primary, secondary = _STATE_LABELS.get(state, ("Jarvis", ""))
        if self.muted:
            secondary = "Muted"

        text_x = cx + orb_r + 14
        font = QFont("Inter", 11)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor(232, 233, 237, int(200 * self._alpha_scale())))
        painter.drawText(QPointF(text_x, cy - 2), primary)

        if secondary:
            sub_font = QFont("Inter", 9)
            painter.setFont(sub_font)
            painter.setPen(QColor(138, 143, 163, int(150 * self._alpha_scale())))
            painter.drawText(QPointF(text_x, cy + 14), secondary)

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        self._paint_frosted_panel(painter, self._panel_rect)

        anim = self._animator
        cx, cy = ORB_CX, ORB_CY
        orb_r = anim.core_radius

        self._paint_sphere(painter, cx, cy, orb_r, anim)
        self._paint_state_label(painter, cx, cy, orb_r, anim.state)

        painter.end()


class FaceWidget(QWidget):
    """Transparent floating HUD hosting the orb panel."""

    _VISIBILITY_POLL_MS = 2000

    def __init__(self) -> None:
        super().__init__()
        # Do NOT use Qt.Tool — on macOS tool windows auto-hide when Jarvis loses
        # focus (switching apps, fullscreen, Spaces), which looks like the orb
        # randomly vanished.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(HUD_W, HUD_H)
        self.setWindowTitle("Jarvis")

        self._drag_pos: QPointF | None = None
        self._interrupt_cb: Callable[[], None] | None = None
        self._shutting_down = False
        self._orb = OrbWidget(self)
        self._orb.setGeometry(0, 0, HUD_W, HUD_H)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._on_stop)

        _try_macos_vibrancy(self)
        self._move_to_default_corner()

        self._visibility_timer = QTimer(self)
        self._visibility_timer.timeout.connect(self._ensure_visible)
        self._visibility_timer.start(self._VISIBILITY_POLL_MS)

    def _move_to_default_corner(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            self.move(geom.width() - 220, geom.height() - 140)

    def _clamp_to_screen(self) -> None:
        """Keep the HUD on-screen after display layout changes."""
        if self.isVisible():
            center = self.frameGeometry().center()
            screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        else:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = max(geom.left(), min(self.x(), geom.right() - w))
        y = max(geom.top(), min(self.y(), geom.bottom() - h))
        if x != self.x() or y != self.y():
            self.move(x, y)

    def _ensure_visible(self) -> None:
        if self._shutting_down:
            return
        if not self.isVisible() or self.isMinimized():
            logger.debug("Orb HUD was hidden — restoring visibility.")
            self.show_overlay()
        else:
            self._clamp_to_screen()

    def shutdown(self) -> None:
        """Allow the window to close during app exit."""
        self._shutting_down = True
        self._visibility_timer.stop()
        self.close()

    @property
    def muted(self) -> bool:
        return self._orb.muted

    def set_interrupt_callback(self, callback: Callable[[], None]) -> None:
        self._interrupt_cb = callback

    def _on_stop(self) -> None:
        if self._interrupt_cb:
            self._interrupt_cb()

    def show_overlay(self) -> None:
        self.showNormal()
        self.raise_()
        self._clamp_to_screen()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        if self._shutting_down:
            event.accept()
            return
        event.ignore()
        self.show_overlay()

    def start_drag(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    @pyqtSlot(str)
    def _apply_state(self, state_name: str) -> None:
        try:
            state = JarvisState[state_name]
        except KeyError:
            return
        self._orb.set_state(state)

    def set_state(self, state: JarvisState) -> None:
        QMetaObject.invokeMethod(
            self,
            "_apply_state",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, state.name),
        )

    @pyqtSlot(str)
    def _apply_budget_level(self, level: str) -> None:
        self._orb.set_budget_level(level)

    def set_budget_level(self, level: str) -> None:
        QMetaObject.invokeMethod(
            self,
            "_apply_budget_level",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, level),
        )

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001
        self._drag_pos = None
