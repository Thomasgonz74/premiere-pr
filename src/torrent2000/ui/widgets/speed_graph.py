"""Per-torrent download/upload speed-over-time graph, drawn by hand with
QPainter -- the project has no charting dependency and this is simple
enough (two polylines on an auto-scaled axis) not to warrant adding one.

SpeedGraphWidget itself has no timer and no knowledge of SessionManager --
it is a pure "given these samples, draw them" widget. SpeedGraphDialog
(ui/dialogs/speed_graph_dialog.py) is what polls SessionManager on a timer
and feeds set_history() the results.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from torrent2000.i18n.translator import tr
from torrent2000.utils.formatting import human_rate

# (download_rate, upload_rate) in bytes/sec, oldest first.
SpeedSample = tuple[int, int]

_COLOR_DOWNLOAD = QColor(0x4C, 0xAF, 0x50)  # green
_COLOR_UPLOAD = QColor(0xE6, 0x7E, 0x22)  # orange
_COLOR_GRID = QColor(128, 128, 128, 60)
_COLOR_AXIS_TEXT = QColor(128, 128, 128)

# The vertical scale never collapses below this many bytes/sec, even if
# every sample so far is exactly 0 -- without a floor, dividing by the
# current max would divide by zero the moment history is all-idle.
_MIN_SCALE_BPS = 1

_MARGIN_LEFT = 48
_MARGIN_RIGHT = 8
_MARGIN_TOP = 10
_MARGIN_BOTTOM = 8
_LEGEND_SWATCH = 10
_LEGEND_GAP = 6
_LEGEND_ROW_H = 16


class SpeedGraphWidget(QWidget):
    """Draws two polylines (download/upload) over the current history
    window. `set_history()` fully replaces the plotted data and repaints;
    the widget itself never mutates or polls the samples it's given."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._samples: list[SpeedSample] = []
        self.setMinimumSize(240, 120)

    def set_history(self, samples: list[SpeedSample]) -> None:
        self._samples = list(samples)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            self._paint(painter)
        finally:
            painter.end()

    # -- drawing ------------------------------------------------------

    def _paint(self, painter: QPainter) -> None:
        plot_rect = QRectF(
            _MARGIN_LEFT,
            _MARGIN_TOP,
            max(1, self.width() - _MARGIN_LEFT - _MARGIN_RIGHT),
            max(1, self.height() - _MARGIN_TOP - _MARGIN_BOTTOM - _LEGEND_ROW_H),
        )

        max_rate = _MIN_SCALE_BPS
        for down, up in self._samples:
            max_rate = max(max_rate, down, up)

        self._draw_grid(painter, plot_rect, max_rate)

        if len(self._samples) >= 2:
            self._draw_curve(painter, plot_rect, max_rate, index=0, color=_COLOR_DOWNLOAD)
            self._draw_curve(painter, plot_rect, max_rate, index=1, color=_COLOR_UPLOAD)

        self._draw_legend(painter)

    def _draw_grid(self, painter: QPainter, rect: QRectF, max_rate: int) -> None:
        painter.setPen(QPen(_COLOR_GRID, 1))
        painter.drawRect(rect)

        # Three horizontal reference lines: top (max), middle, bottom (0).
        for fraction in (0.0, 0.5, 1.0):
            y = rect.bottom() - fraction * rect.height()
            painter.setPen(QPen(_COLOR_GRID, 1))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

            label = human_rate(max_rate * fraction)
            painter.setPen(_COLOR_AXIS_TEXT)
            text_rect = QRectF(0, y - 8, _MARGIN_LEFT - 4, 16)
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, label)

    def _draw_curve(self, painter: QPainter, rect: QRectF, max_rate: int, index: int, color: QColor) -> None:
        count = len(self._samples)
        step = rect.width() / (count - 1)

        points = []
        for i, sample in enumerate(self._samples):
            value = sample[index]
            x = rect.left() + i * step
            fraction = min(1.0, value / max_rate) if max_rate > 0 else 0.0
            y = rect.bottom() - fraction * rect.height()
            points.append(QPointF(x, y))

        painter.setPen(QPen(color, 2))
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)

    def _draw_legend(self, painter: QPainter) -> None:
        y = self.height() - _LEGEND_ROW_H
        x = _MARGIN_LEFT

        for color, key in (
            (_COLOR_DOWNLOAD, "speed_graph.legend_download"),
            (_COLOR_UPLOAD, "speed_graph.legend_upload"),
        ):
            swatch_rect = QRectF(x, y + (_LEGEND_ROW_H - _LEGEND_SWATCH) / 2, _LEGEND_SWATCH, _LEGEND_SWATCH)
            painter.fillRect(swatch_rect, color)
            x += _LEGEND_SWATCH + _LEGEND_GAP

            text = tr(key)
            painter.setPen(self.palette().windowText().color())
            metrics = painter.fontMetrics()
            painter.drawText(QPointF(x, y + _LEGEND_ROW_H - metrics.descent() - 2), text)
            x += metrics.horizontalAdvance(text) + 16
