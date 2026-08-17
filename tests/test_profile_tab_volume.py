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


@pytest.fixture
def tab():
    settings = Settings()
    settings.save = MagicMock()  # avoid touching the real config file on disk
    widget = ProfileTab(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings, MagicMock())
    yield widget, settings


def test_slider_initializes_from_settings():
    settings = Settings()
    settings.audio_volume = 42
    settings.save = MagicMock()
    widget = ProfileTab(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings, MagicMock())
    assert widget.audio_section.volume_slider.value() == 42
    assert widget.audio_section.volume_value_label.text() == "42%"


def test_changing_slider_applies_live_without_saving(tab):
    widget, settings = tab
    received = []
    widget.volume_changed.connect(received.append)

    widget.audio_section.volume_slider.setValue(30)

    assert received == [30]
    assert settings.audio_volume == 30
    assert widget.audio_section.volume_value_label.text() == "30%"
    settings.save.assert_not_called()


def test_slider_release_persists_to_disk(tab):
    widget, settings = tab
    widget.audio_section.volume_slider.setValue(55)
    settings.save.assert_not_called()

    widget.audio_section.volume_slider.sliderReleased.emit()

    settings.save.assert_called_once()


def test_save_button_also_persists_current_slider_value(tab):
    widget, settings = tab
    widget.audio_section.volume_slider.setValue(18)
    settings.save.reset_mock()

    widget._on_save_clicked()

    assert settings.audio_volume == 18
    settings.save.assert_called_once()
