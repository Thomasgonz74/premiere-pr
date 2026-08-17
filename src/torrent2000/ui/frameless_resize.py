"""Frameless-window resize mechanics factored out of MainWindow: dragging
any edge/corner to resize (there is no OS-native resize once
Qt.FramelessWindowHint is set), the resize-cursor watchdog, and the
rounded-corner mask that must be recomputed after every resize/maximize
change.
"""

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QTimer, Qt
from PySide6.QtGui import QCursor, QPainterPath, QRegion
from PySide6.QtWidgets import QApplication

RESIZE_MARGIN = 5  # px band around the frameless window's edge that grabs for resize
# Absolute floor, in logical px at baseline (96) DPI -- see
# compute_min_window_size below for the real, content-derived size this is
# only a safety net for. Also used as FramelessResizeController's fallback
# default before that real size is known.
MIN_WINDOW_SIZE = (640, 420)


def compute_min_window_size(chrome_hints, margin: int) -> tuple[int, int]:
    """The window's real minimum size, derived from the always-visible chrome
    around the tab content -- title bar, tab *bar* (not the tab pages),
    status row, grip row -- rather than a guessed constant. `chrome_hints` is
    each of those rows' own minimumSizeHint()/minimumSize(); they stack
    vertically (heights sum, widths share the row), then `margin` (the outer
    layout's contents margin) is added on every side.

    Deliberately excludes each tab page's own content: QTabWidget's internal
    QStackedWidget reports the MAX minimumSizeHint across every page (not
    just the current one) so switching tabs never resizes the window, which
    means asking the whole central widget would let the single widest tab's
    table (whose columns don't need the full window -- QTableWidget scrolls
    horizontally instead of overlapping) balloon the floor for every tab.
    Tab content is expected to manage its own overflow (a QScrollArea, as in
    AddTorrentTab/ProfileTab, or a table/splitter's own scrollbar), not
    dictate the window's structural floor.

    Font metrics behind minimumSizeHint() already reflect actual DPI/text
    scaling, so this naturally grows with those. Floored by MIN_WINDOW_SIZE
    scaled to the screen's logical DPI so unusually small chrome (or a
    screen queried before it's fully set up) never produces an unreasonably
    tiny window."""
    content_w = max((h.width() for h in chrome_hints), default=0)
    content_h = sum(h.height() for h in chrome_hints)

    screen = QApplication.primaryScreen()
    dpi_scale = screen.logicalDotsPerInch() / 96.0 if screen else 1.0
    floor_w = round(MIN_WINDOW_SIZE[0] * dpi_scale)
    floor_h = round(MIN_WINDOW_SIZE[1] * dpi_scale)
    return (max(content_w + 2 * margin, floor_w), max(content_h + 2 * margin, floor_h))


_CURSOR_FOR_EDGE = {
    "left": Qt.SizeHorCursor,
    "right": Qt.SizeHorCursor,
    "top": Qt.SizeVerCursor,
    "bottom": Qt.SizeVerCursor,
    "top_left": Qt.SizeFDiagCursor,
    "bottom_right": Qt.SizeFDiagCursor,
    "top_right": Qt.SizeBDiagCursor,
    "bottom_left": Qt.SizeBDiagCursor,
}


class FramelessResizeController(QObject):
    """Install via `central.installEventFilter(controller)` -- `window` is
    what actually gets resized/masked, `central` is the margin-band widget
    whose mouse events drive it. central (not window) must own the event
    filter: the title bar/tabs fill the window right up to RESIZE_MARGIN, so
    only central's own thin uncovered band ever sees these events."""

    def __init__(self, window, central, min_size: tuple[int, int] = MIN_WINDOW_SIZE) -> None:
        super().__init__(window)
        self._window = window
        self._central = central
        self._min_size = min_size
        self._resize_edge: str | None = None
        self._resize_start_geometry: QRect | None = None
        self._resize_start_pos = None
        self._corner_radius = 0

        central.installEventFilter(self)

        # The Enter/Leave handlers in eventFilter only fire when the cursor
        # actually crosses central's own background. On the left/right/top
        # edges that background is a razor-thin RESIZE_MARGIN band
        # sandwiched between the title bar/tabs and the screen edge, so a
        # cursor moving with any real speed skips over it between one
        # mouse-move sample and the next -- no Enter, no Leave, and the last
        # resize cursor sticks forever. This timer is a ground-truth
        # backstop that doesn't depend on Enter/Leave delivery at all: it
        # just polls where the cursor actually is and corrects the shape if
        # it's wrong.
        self._cursor_watchdog = QTimer(self)
        # 240ms (was 120ms): now that Enter/Leave handles the everyday
        # re-entry case, this only needs to catch the fast-cursor-skips-the-
        # margin edge case -- an extra ~100ms of stale cursor shape there is
        # imperceptible, and doubling the period roughly halves how often
        # this timer wakes the process.
        self._cursor_watchdog.setInterval(240)
        self._cursor_watchdog.timeout.connect(self._check_cursor_watchdog)
        self._cursor_watchdog.start()

    def set_min_size(self, min_size: tuple[int, int]) -> None:
        """Updates the drag-to-resize floor -- called once MainWindow has
        computed the real content-based size via compute_min_window_size,
        which isn't known yet at __init__ time (central's children aren't
        all built until later in MainWindow.__init__)."""
        self._min_size = min_size

    # -------------------------------------------------------------- corners

    def set_corner_radius(self, radius: int) -> None:
        self._corner_radius = radius
        self.update_corner_mask()

    def update_corner_mask(self) -> None:
        if self._corner_radius <= 0 or self._window.isMaximized():
            self._window.clearMask()
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(self._window.rect()), self._corner_radius, self._corner_radius)
        self._window.setMask(QRegion(path.toFillPolygon().toPolygon()))

    # ---------------------------------------------------------------- edges

    def _edge_at(self, pos) -> str | None:
        w, h = self._central.width(), self._central.height()
        # A position outside central's own bounds isn't on any of its edges,
        # regardless of how close it is to the margin band's threshold --
        # without this, "pos.x() >= w - m" and "pos.y() <= m" stay true for
        # ANY x beyond w or any negative y, so once the cursor is off the
        # window entirely (which is exactly when a caller like the watchdog
        # below needs a real answer of "no edge"), this used to keep
        # reporting whichever edge the cursor last exited through.
        if pos.x() < 0 or pos.y() < 0 or pos.x() > w or pos.y() > h:
            return None
        m = RESIZE_MARGIN
        left, right = pos.x() <= m, pos.x() >= w - m
        top, bottom = pos.y() <= m, pos.y() >= h - m
        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return None

    def _check_cursor_watchdog(self) -> None:
        if self._resize_edge is not None or self._window.isMaximized():
            return
        global_pos = QCursor.pos()
        if not self._window.geometry().contains(global_pos):
            if self._central.cursor().shape() != Qt.ArrowCursor:
                self._central.unsetCursor()
            return
        edge = self._edge_at(self._central.mapFromGlobal(global_pos))
        desired_shape = _CURSOR_FOR_EDGE[edge] if edge else Qt.ArrowCursor
        if self._central.cursor().shape() != desired_shape:
            if edge:
                self._central.setCursor(QCursor(desired_shape))
            else:
                self._central.unsetCursor()

    def _perform_resize(self, global_pos) -> None:
        delta = global_pos - self._resize_start_pos
        geo = QRect(self._resize_start_geometry)
        edge = self._resize_edge
        min_w, min_h = self._min_size

        if "left" in edge:
            new_left = geo.left() + delta.x()
            if geo.right() - new_left + 1 >= min_w:
                geo.setLeft(new_left)
        if "right" in edge:
            geo.setWidth(max(min_w, geo.width() + delta.x()))
        if "top" in edge:
            new_top = geo.top() + delta.y()
            if geo.bottom() - new_top + 1 >= min_h:
                geo.setTop(new_top)
        if "bottom" in edge:
            geo.setHeight(max(min_h, geo.height() + delta.y()))

        self._window.setGeometry(geo)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._central and not self._window.isMaximized():
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove:
                if self._resize_edge is not None and (event.buttons() & Qt.LeftButton):
                    self._perform_resize(event.globalPosition().toPoint())
                    return True
                if not event.buttons():
                    edge = self._edge_at(event.position().toPoint())
                    self._central.setCursor(QCursor(_CURSOR_FOR_EDGE[edge]) if edge else QCursor(Qt.ArrowCursor))
            elif event_type == QEvent.Type.Enter:
                # central only ever receives MouseMove on its own thin
                # RESIZE_MARGIN band (everywhere else is covered by the title
                # bar/tabs), so re-entering the window over a child widget --
                # or from outside the app entirely -- produced no MouseMove
                # on central to refresh the cursor, leaving a stale resize
                # icon stuck until the user happened to hover the margin
                # again. Enter fires reliably on every re-entry regardless of
                # where the cursor lands, so refresh the cursor from it too.
                if self._resize_edge is None:
                    edge = self._edge_at(self._central.mapFromGlobal(QCursor.pos()))
                    self._central.setCursor(QCursor(_CURSOR_FOR_EDGE[edge]) if edge else QCursor(Qt.ArrowCursor))
            elif event_type == QEvent.Type.Leave:
                # Moving from the margin onto a child widget (tabs, title
                # bar) also needs a reset -- once a child is under the
                # cursor, central stops receiving MouseMove entirely.
                if self._resize_edge is None:
                    self._central.unsetCursor()
            elif event_type == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    edge = self._edge_at(event.position().toPoint())
                    if edge is not None:
                        self._resize_edge = edge
                        self._resize_start_geometry = QRect(self._window.geometry())
                        self._resize_start_pos = event.globalPosition().toPoint()
                        return True
            elif event_type == QEvent.Type.MouseButtonRelease:
                if self._resize_edge is not None:
                    self._resize_edge = None
                    self._central.unsetCursor()
                    return True
        return super().eventFilter(obj, event)
