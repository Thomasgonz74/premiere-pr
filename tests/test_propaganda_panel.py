import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.propaganda_panel import _MESSAGE_SPECS, CccpPropagandaPanel


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _all_message_texts() -> set[str]:
    return {tr(key) for _, key in _MESSAGE_SPECS}


def test_shows_a_message_immediately_without_waiting_for_the_timer():
    panel = CccpPropagandaPanel()
    assert panel._message_label.text() != ""
    assert panel._message_label.text() in _all_message_texts()


def test_cycling_advances_through_every_message_before_repeating():
    panel = CccpPropagandaPanel()
    seen = {panel._message_label.text()}
    for _ in range(len(_MESSAGE_SPECS) - 1):
        panel._show_next_message()
        seen.add(panel._message_label.text())
    # A full cycle (length of _MESSAGE_SPECS) must show every distinct
    # message at least once before any repeat -- guards against a lazy
    # "always the same one" or a shuffle bug that skips entries.
    assert seen == _all_message_texts()


def test_accent_color_drives_the_illustration_not_a_fixed_constant():
    panel = CccpPropagandaPanel()
    panel.set_accent_color("#FFFF00")
    assert panel._icon._color.name().upper() == "#FFFF00"
    panel.set_accent_color("#CC1B1B")
    assert panel._icon._color.name().upper() == "#CC1B1B"


def test_start_and_stop_control_the_cycling_timer():
    panel = CccpPropagandaPanel()
    assert not panel._timer.isActive()
    panel.start()
    assert panel._timer.isActive()
    panel.stop()
    assert not panel._timer.isActive()


def test_retranslate_ui_refreshes_the_currently_shown_message_and_header():
    panel = CccpPropagandaPanel()
    panel.retranslate_ui()
    assert panel._header.text() == tr("cccp.propaganda.header")
    assert panel._message_label.text() in _all_message_texts()
