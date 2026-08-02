import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.main_window import RESIZE_MARGIN, MainWindow, _CURSOR_FOR_EDGE


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    win = MainWindow(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        Settings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    win.resize(980, 640)
    win.move(100, 100)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()


def _stale_check(win, global_point, expected_shape):
    # Leave the cursor in a stale resize shape first, exactly like the
    # reported bug (cursor stuck showing a resize icon after leaving the
    # window through the left/right/top edge), then let the watchdog react.
    win._central.setCursor(_CURSOR_FOR_EDGE["left"])
    with patch("torrent2000.ui.main_window.QCursor.pos", return_value=global_point):
        win._check_cursor_watchdog()
    assert win._central.cursor().shape() == expected_shape


@pytest.mark.parametrize(
    "offset",
    [
        (-500, 0),  # far left of the window
        (500, 0),  # far right of the window
        (0, -500),  # far above the window
        (0, 500),  # far below the window
    ],
)
def test_cursor_resets_when_pointer_leaves_via_any_edge(window, offset):
    geo = window.geometry()
    dx, dy = offset
    _stale_check(window, QPoint(geo.center().x() + dx, geo.center().y() + dy), Qt.ArrowCursor)


def test_edge_at_rejects_positions_outside_central_bounds(window):
    # Regression guard for the actual root cause: _edge_at used unbounded
    # comparisons ("pos.x() >= w - m"), so a position far outside central's
    # own rect was still reported as an edge instead of "no edge".
    w, h = window._central.width(), window._central.height()
    assert window._edge_at(QPoint(-500, h // 2)) is None
    assert window._edge_at(QPoint(w + 500, h // 2)) is None
    assert window._edge_at(QPoint(w // 2, -500)) is None
    assert window._edge_at(QPoint(w // 2, h + 500)) is None


@pytest.mark.parametrize(
    "margin_point,expected_shape",
    [
        ("left", Qt.SizeHorCursor),
        ("right", Qt.SizeHorCursor),
        ("top", Qt.SizeVerCursor),
        ("bottom", Qt.SizeVerCursor),
    ],
)
def test_watchdog_still_shows_resize_cursor_on_genuine_margin_hover(window, margin_point, expected_shape):
    geo = window.geometry()
    m = RESIZE_MARGIN
    points = {
        "left": QPoint(geo.left() + 1, geo.center().y()),
        "right": QPoint(geo.right() - 1, geo.center().y()),
        "top": QPoint(geo.center().x(), geo.top() + 1),
        "bottom": QPoint(geo.center().x(), geo.bottom() - 1),
    }
    _stale_check(window, points[margin_point], expected_shape)


def test_watchdog_does_not_fight_an_active_drag(window):
    window._resize_edge = "left"
    with patch("torrent2000.ui.main_window.QCursor.pos", return_value=QPoint(-500, 0)):
        # Must be a no-op mid-drag -- the drag's own mouse-move handling
        # owns the cursor shape until the button is released.
        window._central.setCursor(_CURSOR_FOR_EDGE["left"])
        window._check_cursor_watchdog()
    assert window._central.cursor().shape() == Qt.SizeHorCursor
