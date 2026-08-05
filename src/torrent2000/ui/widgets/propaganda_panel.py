"""The CCCP theme's propaganda side panel: an extra strip of window width,
visible only while that theme is active (see MainWindow._set_cccp_panel_active),
cycling through tongue-in-cheek Soviet-propaganda-style messages thanking the
user for their contribution to the collective and needling anyone who dares
download rather than share. Each message pairs with a small hand-drawn
illustration (star / hammer-and-sickle / gear) -- drawn with QPainter rather
than image assets, the same approach already used for the title bar's own
icons, and safely avoids reusing anyone else's actual poster art.
"""

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.soviet_emblem import paint_hammer_and_sickle

PANEL_WIDTH = 220
# Slower than the original 9s -- long enough to actually read a message
# (some run two sentences) before it flips to the next one.
_MESSAGE_INTERVAL_MS = 17000
_DEFAULT_ICON_COLOR = "#CC1B1B"

# (illustration kind, message translation key) -- cycles through 8 distinct
# illustrations (star / hammer-and-sickle / gear / rising sun / wheat sheaf /
# rocket / factory / raised fist) rather than just 3, so the panel doesn't
# feel as repetitive over a full cycle.
_MESSAGE_SPECS: list[tuple[str, str]] = [
    ("star", "cccp.propaganda.msg_01"),
    ("hammer_sickle", "cccp.propaganda.msg_02"),
    ("gear", "cccp.propaganda.msg_03"),
    ("sun_rays", "cccp.propaganda.msg_04"),
    ("wheat", "cccp.propaganda.msg_05"),
    ("rocket", "cccp.propaganda.msg_06"),
    ("factory", "cccp.propaganda.msg_07"),
    ("fist", "cccp.propaganda.msg_08"),
    ("star", "cccp.propaganda.msg_09"),
    ("hammer_sickle", "cccp.propaganda.msg_10"),
    ("gear", "cccp.propaganda.msg_11"),
    ("sun_rays", "cccp.propaganda.msg_12"),
    ("wheat", "cccp.propaganda.msg_13"),
    ("rocket", "cccp.propaganda.msg_14"),
    ("factory", "cccp.propaganda.msg_15"),
    ("fist", "cccp.propaganda.msg_16"),
    ("star", "cccp.propaganda.msg_17"),
    ("hammer_sickle", "cccp.propaganda.msg_18"),
]


class _PropagandaIcon(QWidget):
    """Hand-drawn (not image-file-based) star / hammer-and-sickle / gear
    silhouette, single-colored to match real constructivist poster
    iconography's flat, high-contrast look."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._kind = "star"
        self._color = QColor(_DEFAULT_ICON_COLOR)
        self.setFixedSize(72, 72)

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.update()

    def set_color(self, color: str) -> None:
        # Driven by MainWindow per (theme, appearance_mode) -- dark_hc needs
        # this to be yellow like every other accent in that mode, not red.
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = self._color
        cx, cy = self.width() / 2, self.height() / 2

        if self._kind == "star":
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(_star_polygon(cx, cy, outer_r=30, inner_r=12))
        elif self._kind == "gear":
            pen = QPen(color, 4)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), 16, 16)
            for i in range(8):
                painter.save()
                painter.translate(cx, cy)
                painter.rotate(i * 45)
                painter.fillRect(QRectF(-3, -30, 6, 10), color)
                painter.restore()
        elif self._kind == "hammer_sickle":
            paint_hammer_and_sickle(painter, cx, cy, 26.0, color)
        elif self._kind == "sun_rays":
            _draw_sun_rays(painter, cx, cy, color)
        elif self._kind == "wheat":
            _draw_wheat(painter, cx, cy, color)
        elif self._kind == "rocket":
            _draw_rocket(painter, cx, cy, color)
        elif self._kind == "factory":
            _draw_factory(painter, cx, cy, color)
        else:  # "fist"
            _draw_fist(painter, cx, cy, color)
        painter.end()


def _star_polygon(cx: float, cy: float, outer_r: float, inner_r: float) -> QPolygonF:
    points = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        r = outer_r if i % 2 == 0 else inner_r
        points.append(QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle)))
    return QPolygonF(points)


def _draw_sun_rays(painter: QPainter, cx: float, cy: float, color: QColor) -> None:
    """A rising sun over a horizon bar -- "the dawn of the collective"."""
    r = 15
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    path = QPainterPath()
    path.moveTo(cx - r, cy)
    path.arcTo(QRectF(cx - r, cy - r, 2 * r, 2 * r), 180, 180)
    path.closeSubpath()
    painter.drawPath(path)
    for i in range(9):
        rad = math.radians(200 - i * 25)
        inner, outer = r * 1.18, r * 1.9
        dirx, diry = math.cos(rad), -math.sin(rad)
        tip = QPointF(cx + outer * dirx, cy + outer * diry)
        base = QPointF(cx + inner * dirx, cy + inner * diry)
        perp = (-diry, dirx)
        p1 = QPointF(base.x() + perp[0] * 3.0, base.y() + perp[1] * 3.0)
        p2 = QPointF(base.x() - perp[0] * 3.0, base.y() - perp[1] * 3.0)
        painter.drawPolygon(QPolygonF([p1, p2, tip]))
    painter.drawRect(QRectF(cx - r * 2.0, cy - 1.5, r * 4.0, 3))


def _draw_wheat(painter: QPainter, cx: float, cy: float, color: QColor) -> None:
    """A tied sheaf of wheat -- the harvest half of the hammer-and-sickle's
    usual wreath, standing on its own as an icon of agricultural plenty."""
    base = QPointF(cx, cy + 24)
    for a in (-50, -30, -10, 10, 30, 50):
        rad = math.radians(90 + a)
        length = 34 - abs(a) * 0.12
        end = QPointF(base.x() + length * math.cos(rad), base.y() - length * math.sin(rad))
        ctrl = QPointF(base.x() + length * 0.55 * math.cos(rad), base.y() - length * 0.55 * math.sin(rad))
        pen = QPen(color, 2.4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        stalk = QPainterPath(base)
        stalk.quadTo(ctrl, end)
        painter.drawPath(stalk)
        painter.save()
        painter.translate(end)
        painter.rotate(-a)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        ear = QPainterPath()
        ear.moveTo(0, 2)
        ear.cubicTo(-4.5, -4, -3.2, -13, 0, -19)
        ear.cubicTo(3.2, -13, 4.5, -4, 0, 2)
        painter.drawPath(ear)
        awn_pen = QPen(color, 1.1)
        painter.setPen(awn_pen)
        for t in (-9, -5, -1):
            painter.drawLine(QPointF(0, t), QPointF(-5.5, t - 3))
            painter.drawLine(QPointF(0, t), QPointF(5.5, t - 3))
        painter.restore()
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawRect(QRectF(base.x() - 5, base.y() - 4, 10, 6))


def _draw_rocket(painter: QPainter, cx: float, cy: float, color: QColor) -> None:
    """An ascending rocket -- the Soviet space program's pride, angled into
    a dynamic climb rather than sitting upright and static."""
    painter.save()
    painter.translate(cx, cy)
    painter.rotate(-25)
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    body = QPainterPath()
    body.moveTo(0, -28)
    body.quadTo(9, -10, 7, 14)
    body.lineTo(-7, 14)
    body.quadTo(-9, -10, 0, -28)
    painter.drawPath(body)
    painter.drawPolygon(QPolygonF([QPointF(-7, 6), QPointF(-17, 21), QPointF(-7, 16)]))
    painter.drawPolygon(QPolygonF([QPointF(7, 6), QPointF(17, 21), QPointF(7, 16)]))
    flame = QPainterPath()
    flame.moveTo(-5, 14)
    flame.quadTo(0, 27, 5, 14)
    flame.closeSubpath()
    painter.drawPath(flame)
    painter.restore()


def _draw_factory(painter: QPainter, cx: float, cy: float, color: QColor) -> None:
    """A factory block with sawtooth roofline and two smoking chimneys --
    industrial output, the other pillar the hammer alone can only gesture at."""
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawRect(QRectF(cx - 24, cy + 2, 48, 20))
    roof = QPainterPath()
    roof.moveTo(cx - 24, cy + 2)
    for i in range(4):
        x0 = cx - 24 + i * 12
        roof.lineTo(x0 + 6, cy - 8)
        roof.lineTo(x0 + 12, cy + 2)
    roof.closeSubpath()
    painter.drawPath(roof)
    painter.drawRect(QRectF(cx - 18, cy - 24, 6, 24))
    painter.drawRect(QRectF(cx + 6, cy - 32, 6, 32))
    painter.drawEllipse(QPointF(cx - 15, cy - 30), 4, 4)
    painter.drawEllipse(QPointF(cx - 11, cy - 37), 5, 5)
    painter.drawEllipse(QPointF(cx + 9, cy - 38), 4, 4)
    painter.drawEllipse(QPointF(cx + 13, cy - 45), 5, 5)


def _draw_fist(painter: QPainter, cx: float, cy: float, color: QColor) -> None:
    """A raised, clenched fist -- solidarity, the poster staple that isn't
    the hammer-and-sickle itself."""
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawRect(QRectF(cx - 8, cy + 8, 16, 20))
    painter.drawRoundedRect(QRectF(cx - 17, cy - 14, 34, 24), 6, 6)
    for dx in (-12, -4, 4, 12):
        painter.drawEllipse(QRectF(cx + dx - 5, cy - 20, 10, 12))
    painter.save()
    painter.translate(cx - 15, cy - 1)
    painter.rotate(-25)
    painter.drawRoundedRect(QRectF(-5, -11, 10, 20), 4, 4)
    painter.restore()


class CccpPropagandaPanel(QWidget):
    """Extra window-width strip shown only under the CCCP theme -- see
    MainWindow._set_cccp_panel_active. Styling (colors, border) comes from
    the CCCP QSS files via #cccpPropagandaPanel/#propagandaHeader/
    #propagandaMessage selectors, not hardcoded here, matching how the rest
    of the app's theming works."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("cccpPropagandaPanel")
        self.setFixedWidth(PANEL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(10)

        self._header = QLabel(tr("cccp.propaganda.header"), self)
        self._header.setObjectName("propagandaHeader")
        self._header.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._header)

        divider = QFrame(self)
        divider.setObjectName("propagandaDivider")
        divider.setFixedHeight(2)
        layout.addWidget(divider)

        layout.addSpacing(6)

        self._icon = _PropagandaIcon(self)
        layout.addWidget(self._icon, 0, Qt.AlignHCenter)

        layout.addSpacing(6)

        self._message_label = QLabel(self)
        self._message_label.setObjectName("propagandaMessage")
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._message_label)

        layout.addStretch(1)

        self._order = list(range(len(_MESSAGE_SPECS)))
        random.shuffle(self._order)
        self._position = -1

        self._timer = QTimer(self)
        self._timer.setInterval(_MESSAGE_INTERVAL_MS)
        self._timer.timeout.connect(self._show_next_message)

        self._show_next_message()

    def _show_next_message(self) -> None:
        self._position += 1
        if self._position >= len(self._order):
            self._position = 0
            random.shuffle(self._order)
        kind, key = _MESSAGE_SPECS[self._order[self._position]]
        self._icon.set_kind(kind)
        self._message_label.setText(tr(key))

    def retranslate_ui(self) -> None:
        self._header.setText(tr("cccp.propaganda.header"))
        # Re-resolve the CURRENTLY shown message in the new language rather
        # than waiting for the next timer tick, so a language switch is
        # reflected immediately like everywhere else in the app.
        if 0 <= self._position < len(self._order):
            _, key = _MESSAGE_SPECS[self._order[self._position]]
            self._message_label.setText(tr(key))

    def set_accent_color(self, color: str) -> None:
        self._icon.set_color(color)

    def start(self) -> None:
        self._show_next_message()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
