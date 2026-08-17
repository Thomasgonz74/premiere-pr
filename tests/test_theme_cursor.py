import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from torrent2000.ui.theme.theme_manager import THEME_LABELS, cursor_for_theme


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("theme_id", [theme_id for _, theme_id in THEME_LABELS])
def test_cursor_for_theme_loads_a_real_pixmap_with_hotspot_inside_bounds(theme_id):
    cursor = cursor_for_theme(theme_id)
    assert cursor is not None
    pixmap = cursor.pixmap()
    assert not pixmap.isNull()
    assert 0 <= cursor.hotSpot().x() < pixmap.width()
    assert 0 <= cursor.hotSpot().y() < pixmap.height()


def test_unknown_theme_id_falls_back_to_the_default_theme_cursor():
    assert cursor_for_theme("not-a-real-theme") is not None


def test_window_level_cursor_is_what_a_child_without_its_own_cursor_inherits():
    # Mirrors MainWindow's actual structure: central = QWidget(self), one hop
    # below the QMainWindow -- FramelessResizeController's central.unsetCursor()
    # calls (on leaving a resize edge) must fall back to *this* cursor, not
    # the raw OS arrow, or the themed pointer would vanish every time the
    # user's mouse crosses the window's resize margin.
    window = QMainWindow()
    central = QWidget(window)
    window.setCentralWidget(central)

    cursor = cursor_for_theme("win95_classic")
    window.setCursor(cursor)

    assert window.testAttribute(Qt.WA_SetCursor)
    assert not central.testAttribute(Qt.WA_SetCursor)  # inherits, doesn't own one

    central.setCursor(Qt.SizeHorCursor)  # simulates hovering a resize edge
    assert central.testAttribute(Qt.WA_SetCursor)
    central.unsetCursor()  # simulates leaving the edge
    assert not central.testAttribute(Qt.WA_SetCursor)  # back to inheriting window's themed cursor
