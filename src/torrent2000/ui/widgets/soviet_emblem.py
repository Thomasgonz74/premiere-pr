"""Shared hammer-and-sickle glyph, drawn as proper filled shapes (a tapered
crescent blade, a stepped hammer head) rather than single-width strokes, so
it actually reads as the real Soviet emblem at both the tiny title-bar close
button size and the larger propaganda-panel icon size. Both call sites share
this one drawing routine so the shape only needs to look right in one place.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF


def _crescent_blade_path(cx: float, cy: float, s: float) -> QPainterPath:
    """The sickle's blade: a curved band that starts thick near the handle
    and tapers to a sharp point, built from two concentric arcs (outer edge,
    inner edge) rather than a constant-width stroke -- a constant-width arc
    is what made the previous attempt unrecognizable as a blade."""
    center = QPointF(cx - s * 0.02, cy - s * 0.30)
    outer_r = s * 0.98
    inner_r = s * 0.60
    start_deg, end_deg = 205.0, 18.0  # sweeps from the lower-left handle end, over the top, to a point near the upper right
    steps = 40
    outer_pts: list[QPointF] = []
    inner_pts: list[QPointF] = []
    for i in range(steps + 1):
        t = i / steps
        deg = start_deg + (end_deg - start_deg) * t
        rad = math.radians(deg)
        # The blade's width collapses to ~0 by the tip (t -> 1), so the two
        # arcs converge into the sharp point real sickle blades taper to.
        taper = t**1.7
        r_in = inner_r + (outer_r - inner_r) * taper
        outer_pts.append(QPointF(center.x() + outer_r * math.cos(rad), center.y() - outer_r * math.sin(rad)))
        inner_pts.append(QPointF(center.x() + r_in * math.cos(rad), center.y() - r_in * math.sin(rad)))

    # A short curling barb past the main point -- the real emblem's blade
    # doesn't just taper to a plain point, it hooks back on itself slightly.
    # Continuing the outer edge a bit further while collapsing its radius
    # curls a thin tail back past where the inner edge already stopped.
    hook_steps = 14
    hook_span_deg = 26.0
    hook_pts: list[QPointF] = []
    for i in range(1, hook_steps + 1):
        t = i / hook_steps
        deg = end_deg - hook_span_deg * t
        rad = math.radians(deg)
        r = outer_r * (1.0 - 0.72 * t)
        hook_pts.append(QPointF(center.x() + r * math.cos(rad), center.y() - r * math.sin(rad)))

    path = QPainterPath()
    path.moveTo(outer_pts[0])
    for p in outer_pts[1:]:
        path.lineTo(p)
    for p in hook_pts:
        path.lineTo(p)
    for p in reversed(inner_pts):
        path.lineTo(p)
    path.closeSubpath()
    return path


def _sickle_handle_polygon(cx: float, cy: float, s: float) -> QPolygonF:
    """Short handle sprouting from the blade's thick (lower-left) end,
    angled almost straight down -- deliberately a steeper angle than the
    hammer's diagonal handle so the two cross distinctly instead of running
    near-parallel and merging into one blob where they meet."""
    base = QPointF(cx - s * 0.80, cy + s * 0.05)
    direction = QPointF(0.05, 0.95)  # nearly straight down, slight right lean
    length = s * 0.55
    width = s * 0.14
    dx, dy = direction.x(), direction.y()
    norm = math.hypot(dx, dy)
    dx, dy = dx / norm, dy / norm
    nx, ny = -dy, dx
    tip = QPointF(base.x() + dx * length, base.y() + dy * length)
    return QPolygonF(
        [
            QPointF(base.x() + nx * width, base.y() + ny * width),
            QPointF(base.x() - nx * width, base.y() - ny * width),
            QPointF(tip.x() - nx * width * 0.15, tip.y() - ny * width * 0.15),
            QPointF(tip.x() + nx * width * 0.15, tip.y() + ny * width * 0.15),
        ]
    )


def _hammer_polygon(cx: float, cy: float, s: float) -> QPolygonF:
    """Hammer head (a mallet block with a small stepped claw on its trailing
    corner, like the real emblem's asymmetric head) plus its handle, as one
    solid polygon crossing down through the sickle toward the lower-left."""
    # Local coordinates before rotation: head sits at the top, handle runs
    # straight down from its center. +x is right, +y is down.
    head_w, head_h = s * 0.95, s * 0.42
    claw_w, claw_h = s * 0.30, s * 0.20
    handle_w, handle_len = s * 0.24, s * 1.30
    pts = [
        QPointF(-head_w / 2, -head_h / 2),
        QPointF(head_w / 2, -head_h / 2),
        QPointF(head_w / 2, head_h / 2),
        QPointF(head_w / 2 - claw_w, head_h / 2),
        QPointF(head_w / 2 - claw_w, head_h / 2 + claw_h),
        QPointF(handle_w / 2, head_h / 2 + claw_h),
        QPointF(handle_w / 2, head_h / 2 + claw_h + handle_len),
        QPointF(-handle_w / 2, head_h / 2 + claw_h + handle_len),
        QPointF(-handle_w / 2, head_h / 2),
        QPointF(-head_w / 2, head_h / 2),
    ]
    angle = math.radians(-48)  # handle runs down-right, crossing the sickle's own down-left handle
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    origin = QPointF(cx - s * 0.18, cy - s * 0.58)
    rotated = [QPointF(origin.x() + p.x() * cos_a - p.y() * sin_a, origin.y() + p.x() * sin_a + p.y() * cos_a) for p in pts]
    return QPolygonF(rotated)


def paint_hammer_and_sickle(painter: QPainter, cx: float, cy: float, size: float, color: QColor) -> None:
    """Paint the emblem centered at (cx, cy); `size` is roughly the glyph's
    radius. Caller is responsible for antialiasing/pen state around this
    call (both current call sites already manage that themselves)."""
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawPolygon(_hammer_polygon(cx, cy, size))
    painter.drawPath(_crescent_blade_path(cx, cy, size))
    painter.drawPolygon(_sickle_handle_polygon(cx, cy, size))
