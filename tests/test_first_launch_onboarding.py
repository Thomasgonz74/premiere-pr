import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.onboarding_dialog import maybe_show_onboarding


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_settings_default_first_launch_seen_to_false():
    assert Settings().first_launch_seen is False


def test_dialog_shown_and_flag_persisted_on_first_launch():
    settings = Settings()
    settings.save = MagicMock()
    assert settings.first_launch_seen is False

    with patch("torrent2000.ui.onboarding_dialog.QMessageBox") as mock_box_cls:
        mock_box = mock_box_cls.return_value
        maybe_show_onboarding(None, settings)

    mock_box.exec.assert_called_once()
    assert settings.first_launch_seen is True
    settings.save.assert_called_once()


def test_dialog_not_shown_when_already_seen():
    settings = Settings(first_launch_seen=True)
    settings.save = MagicMock()

    with patch("torrent2000.ui.onboarding_dialog.QMessageBox") as mock_box_cls:
        maybe_show_onboarding(None, settings)

    mock_box_cls.assert_not_called()
    assert settings.first_launch_seen is True
    settings.save.assert_not_called()
