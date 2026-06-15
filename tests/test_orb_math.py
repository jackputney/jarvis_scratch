"""Pure orb math — no PyQt6 required."""


def point_in_core(cx: float, cy: float, core_radius: float, x: float, y: float) -> bool:
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= core_radius * core_radius


def test_point_in_core_hit():
    assert point_in_core(50, 50, 26, 50, 50) is True


def test_point_in_core_miss():
    assert point_in_core(50, 50, 26, 100, 100) is False
