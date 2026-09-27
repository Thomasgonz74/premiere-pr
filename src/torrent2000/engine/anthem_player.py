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
        # Built on the first start(), not here: QAudioOutput/QMediaPlayer load
        # Qt Multimedia's FFmpeg plugin, enumerate the audio devices and open
        # the MP3 -- a cost every launch would pay for the CCCP theme alone.
        self._audio_output = None
        self._player = None
        self.set_volume(initial_volume_percent)

    def _ensure_player(self) -> None:
        if self._player is not None:  # "is None", so a test's injected mock survives
            return
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(self._volume)
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        path = resource_path(_ANTHEM_ASSET)
        if path.exists():
            self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.setLoops(QMediaPlayer.Loops.Infinite.value)

    def set_volume(self, percent: int) -> None:
        # Remembered until the player exists, then applied live.
        self._volume = max(0, min(100, percent)) / 100.0
        if self._audio_output is not None:
            self._audio_output.setVolume(self._volume)

    def start(self) -> None:
        self._ensure_player()
        if self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._player.play()

    def stop(self) -> None:
        if self._player is not None:  # never started: nothing to stop
            self._player.stop()
