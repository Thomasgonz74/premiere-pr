import os
import time
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from torrent2000.engine.anthem_player import AnthemPlayer


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _wait_until_loaded(player, timeout_s=3.0):
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if player._player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.InvalidMedia,
        ):
            return
        time.sleep(0.02)


def test_loads_the_bundled_mp3_asset():
    player = AnthemPlayer()
    _wait_until_loaded(player)
    assert player._player.source().isValid()
    assert player._player.source().toLocalFile().endswith("cccp_anthem.mp3")
    assert player._player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia
    assert player._player.error() == QMediaPlayer.Error.NoError


def test_loops_forever():
    player = AnthemPlayer()
    assert player._player.loops() == QMediaPlayer.Loops.Infinite.value


@pytest.mark.parametrize("percent,expected", [(0, 0.0), (70, 0.7), (100, 1.0)])
def test_set_volume_converts_percent_to_qt_fraction(percent, expected):
    player = AnthemPlayer()
    player.set_volume(percent)
    assert player._audio_output.volume() == pytest.approx(expected)


def test_set_volume_clamps_out_of_range_input():
    player = AnthemPlayer()
    player.set_volume(150)
    assert player._audio_output.volume() == pytest.approx(1.0)
    player.set_volume(-20)
    assert player._audio_output.volume() == pytest.approx(0.0)


def test_initial_volume_applied_at_construction():
    player = AnthemPlayer(initial_volume_percent=42)
    assert player._audio_output.volume() == pytest.approx(0.42)


def test_start_does_not_replay_if_already_playing():
    player = AnthemPlayer()
    player._player = MagicMock()
    player._player.playbackState.return_value = QMediaPlayer.PlaybackState.StoppedState
    player.start()
    player._player.play.assert_called_once()

    player._player.playbackState.return_value = QMediaPlayer.PlaybackState.PlayingState
    player.start()
    player._player.play.assert_called_once()  # still just the one call


def test_stop_calls_through():
    player = AnthemPlayer()
    player._player = MagicMock()
    player.stop()
    player._player.stop.assert_called_once()
