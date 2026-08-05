import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from torrent2000.config.settings import Settings
from torrent2000.engine.update_checker import UpdateChecker
from torrent2000.ui.main_window import MainWindow


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    settings = Settings()
    settings.save = MagicMock()
    update_checker = UpdateChecker(settings)
    win = MainWindow(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        settings, MagicMock(), MagicMock(), MagicMock(), update_checker,
    )
    yield win, settings, update_checker
    win.close()


def _simulate_click(nth_button: int):
    """Patches QMessageBox so exec() returns immediately and clickedButton()
    reports whichever button (0=Download, 1=Later, matching addButton()
    call order in _on_update_available) the test wants to simulate."""
    return patch.multiple(
        QMessageBox,
        exec=MagicMock(return_value=0),
        clickedButton=lambda self: self.buttons()[nth_button],
    )


def test_update_checker_signal_is_wired_to_the_window(window):
    win, settings, update_checker = window
    with _simulate_click(1):  # "Plus tard" -- avoid opening a real browser during the test
        update_checker.update_available.emit("v9.9.9", "https://example.com")
    assert settings.dismissed_update_version == "v9.9.9"


def test_clicking_download_opens_the_release_page(window):
    win, settings, _ = window
    with _simulate_click(0):  # "Télécharger"
        with patch("torrent2000.ui.main_window.QDesktopServices.openUrl") as mock_open:
            win._on_update_available("v2.0.0", "https://example.com/releases/v2.0.0")
    mock_open.assert_called_once()
    opened_url = mock_open.call_args[0][0]
    assert opened_url.toString() == "https://example.com/releases/v2.0.0"
    assert settings.dismissed_update_version == ""  # only "Later" marks it dismissed


def test_clicking_later_dismisses_without_opening_a_browser(window):
    win, settings, _ = window
    with _simulate_click(1):  # "Plus tard"
        with patch("torrent2000.ui.main_window.QDesktopServices.openUrl") as mock_open:
            win._on_update_available("v2.0.0", "https://example.com/releases/v2.0.0")
    mock_open.assert_not_called()
    assert settings.dismissed_update_version == "v2.0.0"
    settings.save.assert_called_once()
