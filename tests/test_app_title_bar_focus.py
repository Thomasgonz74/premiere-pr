import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from torrent2000.ui.theme.theme_manager import TITLE_BAR_STYLES
from torrent2000.ui.widgets.app_title_bar import AppTitleBar

_BUTTON_ATTRS = ["_minimize_button", "_maximize_button", "_close_button"]


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=list(TITLE_BAR_STYLES.keys()))
def title_bar(request):
    style = TITLE_BAR_STYLES[request.param]
    widget = AppTitleBar("Test Window", style)
    widget.show()
    # Offscreen QPA doesn't auto-activate windows the way a real window
    # manager does, and hasFocus() only reports True for the active
    # window's focus widget -- without this, setFocus() below would
    # silently fail to make the button the focus widget.
    widget.activateWindow()
    QApplication.instance().processEvents()
    yield widget
    widget.close()


def test_caption_buttons_are_keyboard_focusable(title_bar):
    for attr in _BUTTON_ATTRS:
        button = getattr(title_bar, attr)
        assert button.focusPolicy() != Qt.NoFocus


def test_caption_buttons_are_in_focus_chain(title_bar):
    # setFocus() only actually moves focus if the widget's policy permits
    # it -- NoFocus would silently no-op here, so this also proves the
    # buttons are reachable, not just that the enum value changed.
    for attr in _BUTTON_ATTRS:
        button = getattr(title_bar, attr)
        button.setFocus(Qt.TabFocusReason)
        assert button.hasFocus()
        assert QApplication.focusWidget() is button
        button.clearFocus()


@pytest.mark.parametrize("attr", _BUTTON_ATTRS)
def test_space_activates_focused_button(title_bar, attr):
    button = getattr(title_bar, attr)
    received = []
    # A plain function, not received.append directly: PySide can't
    # introspect a builtin method's signature, so it silently connects to
    # the zero-arg clicked() overload and the call raises internally,
    # leaving `received` empty regardless of whether Space worked.
    button.clicked.connect(lambda checked=False: received.append(checked))
    button.setFocus(Qt.TabFocusReason)
    assert button.hasFocus()

    QTest.keyClick(button, Qt.Key_Space)

    assert received, f"Space did not trigger clicked for {attr}"


def test_mouse_click_does_not_grab_focus(title_bar):
    # Mouse-click behavior must stay unchanged: only Tab/programmatic focus
    # should reach these buttons, not a plain click (TabFocus, not
    # StrongFocus). Window activation auto-focuses the first tabbable
    # widget, so focus must be explicitly cleared first to isolate what
    # the click itself does.
    button = title_bar._minimize_button
    button.clearFocus()
    assert not button.hasFocus()

    QTest.mouseClick(button, Qt.LeftButton)

    assert not button.hasFocus()
