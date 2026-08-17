import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from torrent2000.app import _ButtonClickFocusFilter


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    app.installEventFilter(_ButtonClickFocusFilter(app))
    return app


@pytest.fixture
def button(qapp):
    host = QWidget()
    btn = QPushButton("Creer un torrent...", host)
    host.resize(200, 80)
    btn.resize(160, 30)
    host.show()
    host.activateWindow()
    qapp.processEvents()
    yield btn
    host.close()


def test_ordinary_button_switches_to_tab_focus(button):
    # The Polish-time sweep should have already flipped this from the Qt
    # default (StrongFocus) to TabFocus, same policy as app_title_bar.py's
    # caption buttons.
    assert button.focusPolicy() == Qt.TabFocus


def test_mouse_click_does_not_leave_a_focus_ring(button):
    button.clearFocus()
    assert not button.hasFocus()

    QTest.mouseClick(button, Qt.LeftButton)

    assert not button.hasFocus(), "a plain click left the button focused -- fake-hover bug"


def test_tab_focus_still_works(button):
    button.setFocus(Qt.TabFocusReason)

    assert button.hasFocus(), "TabFocus must still let Tab/programmatic focus reach the button"
