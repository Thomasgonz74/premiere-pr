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
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from torrent2000.i18n.translator import tr

PANEL_WIDTH = 220
_MESSAGE_INTERVAL_MS = 9000
_DEFAULT_ICON_COLOR = "#CC1B1B"

# (illustration kind, message translation key) -- illustration kinds cycle
# through the same three hand-drawn icons, message text is what varies.
_MESSAGE_SPECS: list[tuple[str, str]] = [
    ("star", "cccp.propaganda.msg_01"),
    ("hammer_sickle", "cccp.propaganda.msg_02"),
    ("gear", "cccp.propaganda.msg_03"),
    ("star", "cccp.propaganda.msg_04"),
    ("hammer_sickle", "cccp.propaganda.msg_05"),
    ("gear", "cccp.propaganda.msg_06"),
    ("star", "cccp.propaganda.msg_07"),
    ("hammer_sickle", "cccp.propaganda.msg_08"),
    ("gear", "cccp.propaganda.msg_09"),
    ("star", "cccp.propaganda.msg_10"),
    ("hammer_sickle", "cccp.propaganda.msg_11"),
    ("gear", "cccp.propaganda.msg_12"),
    ("star", "cccp.propaganda.msg_13"),
    ("hammer_sickle", "cccp.propaganda.msg_14"),
    ("gear", "cccp.propaganda.msg_15"),
    ("star", "cccp.propaganda.msg_16"),
    ("hammer_sickle", "cccp.propaganda.msg_17"),
    ("gear", "cccp.propaganda.msg_18"),
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
        else:  # "hammer_sickle"
            pen = QPen(color, 5)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            sickle_rect = QRectF(cx - 22, cy - 24, 40, 40)
            painter.drawArc(sickle_rect, -20 * 16, 260 * 16)
            painter.drawLine(QPointF(cx + 17, cy - 21), QPointF(cx + 26, cy - 29))
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(-40)
            painter.drawLine(QPointF(-3, 26), QPointF(-3, -10))
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(-13, -26, 20, 12))
            painter.restore()
        painter.end()


def _star_polygon(cx: float, cy: float, outer_r: float, inner_r: float) -> QPolygonF:
    points = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        r = outer_r if i % 2 == 0 else inner_r
        points.append(QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle)))
    return QPolygonF(points)


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
