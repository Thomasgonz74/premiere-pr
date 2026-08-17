"""Custom-painted caption bar standing in for the native OS title bar.

QSS cannot restyle the OS-owned window frame, so the main window is created
frameless and this widget paints the caption itself: background (gradient
for XP/7, flat for 10/11/macOS/CCCP), icon, title, and the minimize/
maximize/close buttons, plus click-drag-to-move and double-click-to-
maximize. Its exact look -- including macOS's left-aligned circular
traffic lights, the one variant with a fundamentally different button
layout rather than just different colors -- is driven by a TitleBarStyle
(see theme/theme_manager.py) so the same widget serves every theme.
"""

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from torrent2000.i18n.translator import tr
from torrent2000.ui.theme.theme_manager import TitleBarStyle
from torrent2000.ui.widgets.soviet_emblem import paint_hammer_and_sickle
from torrent2000.utils.resource_path import resource_path

TITLE_BAR_HEIGHT = 30
_BUTTON_SIZE = 21
_MAC_BUTTON_SIZE = 14

_MODERN_HOVER_MIN_MAX_LIGHT = "#E5E5E5"
_MODERN_HOVER_MIN_MAX_DARK = "#3A3A3A"
_MODERN_HOVER_CLOSE = "#E81123"

# Real macOS traffic lights are always red/yellow/green regardless of the
# system's light/dark/high-contrast appearance -- so unlike every other
# button_variant, these are hardcoded here rather than sourced from
# TitleBarStyle.
_MAC_CLOSE_FILL = "#FF5F57"
_MAC_CLOSE_HOVER = "#FF453A"
_MAC_MINIMIZE_FILL = "#FEBC2E"
_MAC_MINIMIZE_HOVER = "#FFB01E"
_MAC_MAXIMIZE_FILL = "#28C840"
_MAC_MAXIMIZE_HOVER = "#1DAD34"
_MAC_GLYPH_COLOR = "#4D0000"

# Hand-painted buttons get no QSS :focus styling, so the keyboard focus
# indicator is drawn here as two overlapping dashed rects, one black one
# white, offset in dash phase -- "marching ants" that stay visible against
# any fill color (XP blue, modern hover-gray, or any of the mac traffic-
# light colors) without needing a per-variant color to be hand-picked.
_FOCUS_RING_DARK = "#000000"
_FOCUS_RING_LIGHT = "#FFFFFF"


class _CaptionButton(QPushButton):
    """A caption button that paints its own glyph -- either the XP style
    (a colored square with a white-outlined glyph) or the "modern" style
    shared by 7/10/11 (transparent until hover, then a light/red highlight
    with a thin glyph, the close button's glyph turning white on hover)."""

    def __init__(self, glyph: str, parent=None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._variant = "xp"
        self._fill_color = QColor("#3D6FC9")
        self._hover_color = QColor("#5C8CE0")
        self._glyph_color = QColor("#FFFFFF")
        self._hover_glyph_color: QColor | None = None
        self._hover_radius = 0
        self._close_glyph_style = "x"
        self.setFixedSize(_BUTTON_SIZE, TITLE_BAR_HEIGHT - 11)
        self.setFlat(True)
        self.setCursor(Qt.ArrowCursor)
        # TabFocus (not StrongFocus): reachable via Tab/setFocus() so a
        # keyboard-only user can minimize/maximize/close, but mouse clicks
        # still don't grab focus, leaving hover/click visuals unchanged.
        self.setFocusPolicy(Qt.TabFocus)
        self.setStyleSheet("QPushButton { border: none; background: transparent; }")

    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.update()

    def apply_style(self, style: TitleBarStyle) -> None:
        self._variant = style.button_variant
        self._hover_radius = style.button_hover_radius
        if style.button_variant == "xp":
            if self._glyph == "close":
                self._fill_color, self._hover_color = QColor(style.close_fill_color), QColor(style.close_hover_color)
            else:
                self._fill_color, self._hover_color = QColor(style.minmax_fill_color), QColor(style.minmax_hover_color)
            self._glyph_color = QColor(style.button_glyph_color)
            self._hover_glyph_color = (
                QColor(style.button_hover_glyph_color) if style.button_hover_glyph_color else None
            )
            self._close_glyph_style = style.close_glyph
            self.setFixedSize(_BUTTON_SIZE, TITLE_BAR_HEIGHT - 11)
        elif style.button_variant == "mac":
            if self._glyph == "close":
                self._fill_color, self._hover_color = QColor(_MAC_CLOSE_FILL), QColor(_MAC_CLOSE_HOVER)
            elif self._glyph == "min":
                self._fill_color, self._hover_color = QColor(_MAC_MINIMIZE_FILL), QColor(_MAC_MINIMIZE_HOVER)
            else:  # "max" / "restore"
                self._fill_color, self._hover_color = QColor(_MAC_MAXIMIZE_FILL), QColor(_MAC_MAXIMIZE_HOVER)
            self._glyph_color = QColor(_MAC_GLYPH_COLOR)
            self._hover_glyph_color = None
            self._close_glyph_style = "x"
            self.setFixedSize(_MAC_BUTTON_SIZE, _MAC_BUTTON_SIZE)
        else:
            # "modern" glyphs track the caption's own text color, so they
            # stay legible whether the title bar is light or dark.
            self._glyph_color = QColor(style.title_text_color)
            is_dark_caption = QColor(style.title_text_color).lightness() > 128
            hover_min_max = _MODERN_HOVER_MIN_MAX_DARK if is_dark_caption else _MODERN_HOVER_MIN_MAX_LIGHT
            self._hover_color = QColor(_MODERN_HOVER_CLOSE if self._glyph == "close" else hover_min_max)
            self._close_glyph_style = "x"
            self.setFixedSize(_BUTTON_SIZE, TITLE_BAR_HEIGHT - 11)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)
        hovering = self.underMouse() and self.isEnabled()

        if self._variant == "xp":
            fill = self._hover_color if hovering else self._fill_color
            painter.fillRect(rect, fill)
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
            painter.drawRect(rect)
            glyph_color = self._hover_glyph_color if (hovering and self._hover_glyph_color is not None) else self._glyph_color
            painter.setPen(QPen(glyph_color, 1))
        elif self._variant == "mac":
            painter.setRenderHint(QPainter.Antialiasing, True)
            fill = self._hover_color if hovering else self._fill_color
            painter.setBrush(fill)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(rect)
            glyph_color = self._glyph_color
            painter.setPen(QPen(glyph_color, 1.4))
        else:
            painter.setRenderHint(QPainter.Antialiasing, True)
            if hovering:
                path = QPainterPath()
                path.addRoundedRect(QRectF(rect), self._hover_radius, self._hover_radius)
                painter.fillPath(path, self._hover_color)
            painter.setRenderHint(QPainter.Antialiasing, False)
            # Close's glyph turns white against its red hover fill, matching
            # real Windows 10/11 behavior; min/max stay dark on their light
            # gray hover fill.
            glyph_color = QColor("#FFFFFF") if (hovering and self._glyph == "close") else self._glyph_color
            painter.setPen(QPen(glyph_color, 1))

        cx, cy = rect.center().x(), rect.center().y()
        if self._glyph == "min":
            painter.drawLine(cx - 4, cy + 4, cx + 4, cy + 4)
        elif self._glyph == "max":
            painter.drawRect(cx - 4, cy - 4, 8, 8)
        elif self._glyph == "restore":
            painter.drawRect(cx - 5, cy - 1, 6, 6)
            if self._variant == "xp":
                fill = self._hover_color if hovering else self._fill_color
                painter.fillRect(cx - 4, cy - 4, 6, 6, fill)
            painter.drawRect(cx - 4, cy - 4, 6, 6)
        elif self._glyph == "close":
            if self._close_glyph_style == "hammer_sickle":
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing, True)
                paint_hammer_and_sickle(painter, cx, cy, 8.0, glyph_color)
                painter.setRenderHint(QPainter.Antialiasing, False)
                painter.restore()
            else:
                painter.drawLine(cx - 4, cy - 4, cx + 4, cy + 4)
                painter.drawLine(cx - 4, cy + 4, cx + 4, cy - 4)

        if self.hasFocus():
            painter.setRenderHint(QPainter.Antialiasing, False)
            focus_rect = rect.adjusted(2, 2, -2, -2)
            pen = QPen(QColor(_FOCUS_RING_DARK))
            pen.setStyle(Qt.DashLine)
            pen.setWidth(1)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(pen)
            painter.drawRect(focus_rect)
            pen.setColor(QColor(_FOCUS_RING_LIGHT))
            pen.setDashOffset(3)
            painter.setPen(pen)
            painter.drawRect(focus_rect)

        painter.end()


class AppTitleBar(QWidget):
    """Frameless-window stand-in for the native title bar, themeable via
    apply_style()."""

    def __init__(self, title: str, style: TitleBarStyle, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("appTitleBar")
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self._drag_offset: QPoint | None = None
        self._style = style

        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(16, 16)
        icon_path = resource_path("assets/icon.ico")
        if icon_path.exists():
            self._icon_label.setPixmap(QIcon(str(icon_path)).pixmap(16, 16))

        self._title_label = QLabel(title, self)

        self._minimize_button = _CaptionButton("min", self)
        self._minimize_button.setToolTip(tr("titlebar.minimize"))
        self._minimize_button.clicked.connect(self._on_minimize)

        self._maximize_button = _CaptionButton("max", self)
        self._maximize_button.setToolTip(tr("titlebar.maximize"))
        self._maximize_button.clicked.connect(self._on_maximize_restore)

        self._close_button = _CaptionButton("close", self)
        self._close_button.setToolTip(tr("titlebar.close"))
        self._close_button.clicked.connect(self._on_close)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 4, 0)
        self._layout.setSpacing(6)
        self._is_mac_layout = False
        self._build_layout(mac_layout=(style.button_variant == "mac"))

        self.apply_style(style)

    def _build_layout(self, mac_layout: bool) -> None:
        # macOS puts its traffic lights on the LEFT with a centered title,
        # the reverse of every other theme here (buttons on the right,
        # left-aligned title next to the icon) -- different enough that it
        # needs its own widget order, not just different colors, so the
        # whole layout is torn down and rebuilt when the variant changes.
        while self._layout.count():
            self._layout.takeAt(0)
        if mac_layout:
            self._layout.addWidget(self._close_button)
            self._layout.addWidget(self._minimize_button)
            self._layout.addWidget(self._maximize_button)
            self._layout.addStretch(1)
            self._layout.addWidget(self._title_label)
            self._layout.addStretch(1)
            # Invisible spacer roughly matching the traffic-light cluster's
            # width, so the centered title is actually centered instead of
            # skewed toward the right by the unbalanced left-side buttons.
            cluster_width = 3 * _MAC_BUTTON_SIZE + 2 * self._layout.spacing()
            self._layout.addSpacing(cluster_width)
            self._icon_label.hide()
            self._title_label.setAlignment(Qt.AlignCenter)
        else:
            self._layout.addWidget(self._icon_label)
            self._layout.addWidget(self._title_label)
            self._layout.addStretch(1)
            self._layout.addWidget(self._minimize_button)
            self._layout.addWidget(self._maximize_button)
            self._layout.addWidget(self._close_button)
            self._icon_label.show()
            self._title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._is_mac_layout = mac_layout

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def apply_style(self, style: TitleBarStyle) -> None:
        self._style = style
        if (style.button_variant == "mac") != self._is_mac_layout:
            self._build_layout(mac_layout=(style.button_variant == "mac"))
        font = self._title_label.font()
        font.setFamily(style.font_family)
        font.setBold(style.font_bold)
        self._title_label.setFont(font)
        self._title_label.setStyleSheet(f"color: {style.title_text_color}; background: transparent;")
        for button in (self._minimize_button, self._maximize_button, self._close_button):
            button.apply_style(style)
        self.update()

    def refresh_maximize_glyph(self) -> None:
        window = self.window()
        self._maximize_button.set_glyph("restore" if window.isMaximized() else "max")
        self._maximize_button.setToolTip(tr("titlebar.restore") if window.isMaximized() else tr("titlebar.maximize"))

    def retranslate_ui(self) -> None:
        self._minimize_button.setToolTip(tr("titlebar.minimize"))
        self._close_button.setToolTip(tr("titlebar.close"))
        self.refresh_maximize_glyph()

    # -- painting -----------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        if self._style.caption_gradient is not None:
            left, right = self._style.caption_gradient
            gradient = QLinearGradient(0, 0, self.width(), 0)
            gradient.setColorAt(0.0, QColor(left))
            gradient.setColorAt(1.0, QColor(right))
            painter.fillRect(self.rect(), gradient)
        else:
            painter.fillRect(self.rect(), QColor(self._style.caption_flat_color))
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
