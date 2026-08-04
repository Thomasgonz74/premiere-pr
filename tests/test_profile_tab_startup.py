import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.tabs.profile_tab import ProfileTab


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_tab(registry_enabled: bool):
    settings = Settings()
    settings.save = MagicMock()
    with patch("torrent2000.ui.tabs.profile_tab.startup_registration") as mock_sr:
        mock_sr.is_launch_at_startup_enabled.return_value = registry_enabled
        widget = ProfileTab(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings, MagicMock())
    return widget, settings, mock_sr


def test_checkbox_reflects_real_registry_state_not_stale_settings():
    # settings.launch_at_startup defaults to False, but the real registry
    # says it's enabled (e.g. set by hand, or a stale settings.json) -- the
    # checkbox must trust the registry, the actual ground truth.
    widget, settings, _ = _make_tab(registry_enabled=True)
    assert settings.launch_at_startup is False
    assert widget.launch_at_startup_checkbox.isChecked() is True


def test_checkbox_unchecked_when_registry_has_no_entry():
    widget, _, _ = _make_tab(registry_enabled=False)
    assert widget.launch_at_startup_checkbox.isChecked() is False


def test_save_writes_checkbox_state_to_registry_and_settings():
    widget, settings, _ = _make_tab(registry_enabled=False)
    widget.launch_at_startup_checkbox.setChecked(True)

    with patch("torrent2000.ui.tabs.profile_tab.startup_registration") as mock_sr_on_save:
        widget._on_save_clicked()

    assert settings.launch_at_startup is True
    mock_sr_on_save.set_launch_at_startup.assert_called_once_with(True)


def test_save_unregisters_when_unchecked():
    widget, settings, _ = _make_tab(registry_enabled=True)
    widget.launch_at_startup_checkbox.setChecked(False)

    with patch("torrent2000.ui.tabs.profile_tab.startup_registration") as mock_sr_on_save:
        widget._on_save_clicked()

    assert settings.launch_at_startup is False
    mock_sr_on_save.set_launch_at_startup.assert_called_once_with(False)
