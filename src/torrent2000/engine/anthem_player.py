"""Loops the CCCP theme's anthem for as long as that theme stays active.

Uses QMediaPlayer/QAudioOutput rather than QSoundEffect: the bundled asset
(assets/audio/cccp_anthem.mp3) is a compressed MP3, and QSoundEffect's
lightweight backend only decodes uncompressed formats (it reports a load
Error on MP3 in this Qt build) -- QMediaPlayer routes through the full
multimedia backend (FFmpeg plugin), which decodes it correctly and also
gives native infinite-loop support via setLoops().
"""

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from torrent2000.utils.resource_path import resource_path

_ANTHEM_ASSET = "assets/audio/cccp_anthem.mp3"


class AnthemPlayer:
    def __init__(self, initial_volume_percent: int = 70) -> None:
        self._audio_output = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        path = resource_path(_ANTHEM_ASSET)
        if path.exists():
            self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.setLoops(QMediaPlayer.Loops.Infinite.value)
        self.set_volume(initial_volume_percent)

    def set_volume(self, percent: int) -> None:
        self._audio_output.setVolume(max(0, min(100, percent)) / 100.0)

    def start(self) -> None:
        if self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._player.play()

    def stop(self) -> None:
        self._player.stop()
