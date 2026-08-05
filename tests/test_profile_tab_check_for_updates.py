import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.tabs.profile_tab import ProfileTab


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_tab(check_for_updates: bool):
    settings = Settings()
    settings.check_for_updates = check_for_updates
    settings.save = MagicMock()
    widget = ProfileTab(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings, MagicMock())
    return widget, settings


def test_checkbox_initializes_from_settings_enabled():
    widget, _ = _make_tab(check_for_updates=True)
    assert widget.check_for_updates_checkbox.isChecked() is True


def test_checkbox_initializes_from_settings_disabled():
    widget, _ = _make_tab(check_for_updates=False)
    assert widget.check_for_updates_checkbox.isChecked() is False


def test_save_persists_the_checkbox_state():
    widget, settings = _make_tab(check_for_updates=True)
    widget.check_for_updates_checkbox.setChecked(False)

    widget._on_save_clicked()

    assert settings.check_for_updates is False
