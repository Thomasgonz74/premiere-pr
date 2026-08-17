import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from torrent2000.ui.theme.theme_manager import TITLE_BAR_STYLES
from torrent2000.ui.widgets.app_title_bar import AppTitleBar


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _mouse_event(event_type, global_pos, button=Qt.NoButton, buttons=Qt.NoButton):
    # localPos is irrelevant here -- mousePressEvent/mouseMoveEvent only
    # read globalPosition()/button()/buttons(), never the widget-local
    # point -- so the same value is reused for both positional args.
    pos = QPointF(global_pos)
    return QMouseEvent(event_type, pos, pos, button, buttons, Qt.NoModifier)


@pytest.fixture
def window_and_bar():
    # A bare frameless top-level widget standing in for MainWindow (which
    # sets the same flags -- see main_window.py), with AppTitleBar as its
    # child so title_bar.window() resolves to it, exactly like production.
    window = QWidget()
    window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
    window.resize(400, 300)
    title_bar = AppTitleBar("Test Window", TITLE_BAR_STYLES["luna_xp"], window)
    window.show()
    window.move(100, 100)
    QApplication.instance().processEvents()
    yield window, title_bar
    window.close()


def test_press_then_drag_moves_window_by_the_mouse_delta(window_and_bar):
    window, title_bar = window_and_bar

    press_event = _mouse_event(QEvent.Type.MouseButtonPress, QPoint(150, 150), button=Qt.LeftButton, buttons=Qt.LeftButton)
    title_bar.mousePressEvent(press_event)
    assert title_bar._drag_offset == QPoint(50, 50)

    move_event = _mouse_event(QEvent.Type.MouseMove, QPoint(200, 220), buttons=Qt.LeftButton)
    title_bar.mouseMoveEvent(move_event)

    assert window.pos() == QPoint(150, 170)


def test_right_click_does_not_start_a_drag(window_and_bar):
    window, title_bar = window_and_bar

    press_event = _mouse_event(QEvent.Type.MouseButtonPress, QPoint(150, 150), button=Qt.RightButton, buttons=Qt.RightButton)
    title_bar.mousePressEvent(press_event)

    assert title_bar._drag_offset is None


def test_move_without_a_prior_press_does_not_move_window(window_and_bar):
    window, title_bar = window_and_bar
    original_pos = window.pos()

    move_event = _mouse_event(QEvent.Type.MouseMove, QPoint(500, 500), buttons=Qt.LeftButton)
    title_bar.mouseMoveEvent(move_event)

    assert window.pos() == original_pos


def test_mouse_release_clears_drag_offset_and_stops_further_dragging(window_and_bar):
    window, title_bar = window_and_bar

    press_event = _mouse_event(QEvent.Type.MouseButtonPress, QPoint(150, 150), button=Qt.LeftButton, buttons=Qt.LeftButton)
    title_bar.mousePressEvent(press_event)
    assert title_bar._drag_offset is not None

    release_event = _mouse_event(QEvent.Type.MouseButtonRelease, QPoint(150, 150), button=Qt.LeftButton)
    title_bar.mouseReleaseEvent(release_event)
    assert title_bar._drag_offset is None

    pos_after_release = window.pos()
    move_event = _mouse_event(QEvent.Type.MouseMove, QPoint(999, 999), buttons=Qt.LeftButton)
    title_bar.mouseMoveEvent(move_event)
    assert window.pos() == pos_after_release


def test_double_click_maximizes_then_restores(window_and_bar):
    window, title_bar = window_and_bar
    assert not window.isMaximized()
    assert title_bar._maximize_button._glyph == "max"

    dbl_click = _mouse_event(QEvent.Type.MouseButtonDblClick, QPoint(150, 105), button=Qt.LeftButton)
    title_bar.mouseDoubleClickEvent(dbl_click)
    QApplication.instance().processEvents()

    assert window.isMaximized()
    assert title_bar._maximize_button._glyph == "restore"

    title_bar.mouseDoubleClickEvent(dbl_click)
    QApplication.instance().processEvents()

    assert not window.isMaximized()
    assert title_bar._maximize_button._glyph == "max"


def test_right_click_double_click_does_not_toggle_maximize(window_and_bar):
    window, title_bar = window_and_bar

    dbl_click = _mouse_event(QEvent.Type.MouseButtonDblClick, QPoint(150, 105), button=Qt.RightButton)
    title_bar.mouseDoubleClickEvent(dbl_click)

    assert not window.isMaximized()


def test_dragging_a_maximized_window_restores_it_first(window_and_bar):
    window, title_bar = window_and_bar
    window.showMaximized()
    QApplication.instance().processEvents()
    assert window.isMaximized()
    maximized_top_left = window.frameGeometry().topLeft()

    press_global = maximized_top_left + QPoint(60, 15)
    press_event = _mouse_event(QEvent.Type.MouseButtonPress, press_global, button=Qt.LeftButton, buttons=Qt.LeftButton)
    title_bar.mousePressEvent(press_event)
    drag_offset = title_bar._drag_offset
    assert drag_offset == QPoint(60, 15)

    move_global = press_global + QPoint(50, 70)
    move_event = _mouse_event(QEvent.Type.MouseMove, move_global, buttons=Qt.LeftButton)
    title_bar.mouseMoveEvent(move_event)
    QApplication.instance().processEvents()

    # "Restore first so the window follows the cursor naturally" -- the
    # window must no longer be maximized, its glyph must reflect that, and
    # it must have actually moved to follow the cursor (not stayed put).
    assert not window.isMaximized()
    assert title_bar._maximize_button._glyph == "max"
    assert window.pos() == move_global - drag_offset
