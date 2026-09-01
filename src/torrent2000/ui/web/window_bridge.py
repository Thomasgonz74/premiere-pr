"""QWebChannel bridge for window chrome: drag-to-move, edge-resize, and the
minimize/maximize/close buttons -- the piece that has to exist because a
QWebEngineView swallows mouse events before they ever reach a parent
QWidget's mousePressEvent (confirmed empirically this session). JS calls
these slots instead of relying on Qt event bubbling.
"""

from PySide6.QtCore import QObject, Qt, Slot

# Must match the CCCP propaganda panel's CSS width (style.css
# .cccp-propaganda-panel) -- the window itself grows/shrinks by this exact
# amount when the panel appears/disappears, same behavior as the native
# MainWindow._set_cccp_panel_active (ui/widgets/propaganda_panel.PANEL_WIDTH).
_PROPAGANDA_PANEL_WIDTH = 220

_RESIZE_EDGES = {
    "top": Qt.Edge.TopEdge,
    "bottom": Qt.Edge.BottomEdge,
    "left": Qt.Edge.LeftEdge,
    "right": Qt.Edge.RightEdge,
    "top-left": Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
    "top-right": Qt.Edge.TopEdge | Qt.Edge.RightEdge,
    "bottom-left": Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
    "bottom-right": Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
}


class WindowBridge(QObject):
    def __init__(self, window, settings, anthem_player, parent=None) -> None:
        super().__init__(parent)
        self._window = window
        self._settings = settings
        self._anthem_player = anthem_player
        self._propaganda_panel_active = False

    @Slot()
    def startMove(self) -> None:
        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    @Slot(str)
    def startResize(self, edge: str) -> None:
        handle = self._window.windowHandle()
        if handle is None:
            return
        edge_flags = _RESIZE_EDGES.get(edge)
        if edge_flags is not None:
            handle.startSystemResize(edge_flags)

    @Slot()
    def minimize(self) -> None:
        self._window.showMinimized()

    @Slot()
    def toggleMaximize(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    @Slot()
    def close(self) -> None:
        self._window.close()

    @Slot(result=bool)
    def isMaximized(self) -> bool:
        return self._window.isMaximized()

    @Slot(bool)
    def setPropagandaPanelActive(self, active: bool) -> None:
        # Mirrors native MainWindow._set_cccp_panel_active exactly, including
        # its guard against redundant calls: JS calls this on every theme
        # switch (not just ones involving CCCP), so without the guard,
        # switching between two non-CCCP themes would still shrink the
        # window every time. Also drives the anthem, same activation toggle
        # as the panel itself in the native version.
        if active == self._propaganda_panel_active:
            return
        self._propaganda_panel_active = active
        if active:
            self._window.resize(self._window.width() + _PROPAGANDA_PANEL_WIDTH, self._window.height())
            self._anthem_player.start()
        else:
            new_width = max(self._window.minimumWidth(), self._window.width() - _PROPAGANDA_PANEL_WIDTH)
            self._window.resize(new_width, self._window.height())
            self._anthem_player.stop()

    @Slot(result=bool)
    def shouldShowOnboarding(self) -> bool:
        return not self._settings.first_launch_seen

    @Slot()
    def markOnboardingSeen(self) -> None:
        self._settings.first_launch_seen = True
        self._settings.save()
