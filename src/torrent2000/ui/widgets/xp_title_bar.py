"""Custom-painted Windows XP "Luna" caption bar.

QSS cannot restyle the OS-owned window frame/title bar (on Windows 11 that
frame is a native dark title bar, nothing like XP), so to make Torrent 2000
actually look like a real XP window -- horizontal blue gradient caption,
bold white title, red close button -- the main window is created frameless
(see MainWindow) and this widget stands in for the native title bar: it
paints the gradient + icon + title, hosts the minimize/maximize/close
buttons, and implements click-drag-to-move plus double-click-to-maximize.
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from torrent2000.utils.resource_path import resource_path

TITLE_BAR_HEIGHT = 30

# Horizontal gradient, lighter blue on the left blending to the darker
# "active caption" blue on the right -- matches the reference XP screenshots.
CAPTION_LIGHT = QColor("#3169C6")
CAPTION_DARK = QColor("#0A246A")

_BUTTON_SIZE = 21


class _CaptionButton(QPushButton):
    """A small flat XP caption button that paints its own glyph.

    minimize/maximize get a blue-ish fill so they read as part of the
    caption; close is distinctly red, both per the reference screenshots,
    and brightens further on hover.
    """

    def __init__(self, glyph: str, fill_color: str, hover_color: str, parent=None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._fill_color = QColor(fill_color)
        self._hover_color = QColor(hover_color)
        self.setFixedSize(_BUTTON_SIZE, TITLE_BAR_HEIGHT - 11)
        self.setFlat(True)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("QPushButton { border: none; background: transparent; }")

    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)

        fill = self._hover_color if (self.underMouse() and self.isEnabled()) else self._fill_color
        painter.fillRect(rect, fill)
        painter.setPen(QPen(QColor("#FFFFFF"), 1))
        painter.drawRect(rect)

        cx = rect.center().x()
        cy = rect.center().y()
        if self._glyph == "min":
            painter.drawLine(cx - 4, cy + 4, cx + 4, cy + 4)
        elif self._glyph == "max":
            painter.drawRect(cx - 4, cy - 4, 8, 8)
        elif self._glyph == "restore":
            painter.drawRect(cx - 5, cy - 1, 6, 6)
            painter.fillRect(cx - 4, cy - 4, 6, 6, fill)
            painter.drawRect(cx - 4, cy - 4, 6, 6)
        elif self._glyph == "close":
            painter.drawLine(cx - 4, cy - 4, cx + 4, cy + 4)
            painter.drawLine(cx - 4, cy + 4, cx + 4, cy - 4)
        painter.end()


class XPTitleBar(QWidget):
    """Frameless-window stand-in for the native XP title bar."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("xpTitleBar")
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self._drag_offset: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(16, 16)
        icon_path = resource_path("assets/icon.ico")
        if icon_path.exists():
            self._icon_label.setPixmap(QIcon(str(icon_path)).pixmap(16, 16))
        layout.addWidget(self._icon_label)

        self._title_label = QLabel(title, self)
        font = self._title_label.font()
        font.setBold(True)
        self._title_label.setFont(font)
        self._title_label.setStyleSheet("color: #FFFFFF; background: transparent;")
        layout.addWidget(self._title_label)

        layout.addStretch(1)

        self._minimize_button = _CaptionButton("min", "#3D6FC9", "#5C8CE0", self)
        self._minimize_button.setToolTip("Réduire")
        self._minimize_button.clicked.connect(self._on_minimize)
        layout.addWidget(self._minimize_button)

        self._maximize_button = _CaptionButton("max", "#3D6FC9", "#5C8CE0", self)
        self._maximize_button.setToolTip("Agrandir")
        self._maximize_button.clicked.connect(self._on_maximize_restore)
        layout.addWidget(self._maximize_button)

        self._close_button = _CaptionButton("close", "#D42A2A", "#F04A3C", self)
        self._close_button.setToolTip("Fermer")
        self._close_button.clicked.connect(self._on_close)
        layout.addWidget(self._close_button)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def refresh_maximize_glyph(self) -> None:
        window = self.window()
        self._maximize_button.set_glyph("restore" if window.isMaximized() else "max")
        self._maximize_button.setToolTip("Restaurer" if window.isMaximized() else "Agrandir")

    # -- painting -----------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0.0, CAPTION_LIGHT)
        gradient.setColorAt(1.0, CAPTION_DARK)
        painter.fillRect(self.rect(), gradient)
        painter.end()
        super().paintEvent(event)

    # -- caption button actions -----------------------------------------

    def _on_minimize(self) -> None:
        self.window().showMinimized()

    def _on_maximize_restore(self) -> None:
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()
        self.refresh_maximize_glyph()

    def _on_close(self) -> None:
        # Calling close() (not QApplication.quit()/sys.exit()) is required
        # so MainWindow.closeEvent() still runs its graceful BitTorrent
        # session + stats database shutdown.
        self.window().close()

    # -- drag to move / double-click to maximize -------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            window = self.window()
            if window.isMaximized():
                # Restore first so the window follows the cursor naturally,
                # matching real Windows drag-to-restore behavior.
                window.showNormal()
                self.refresh_maximize_glyph()
            window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._on_maximize_restore()
        else:
            super().mouseDoubleClickEvent(event)
