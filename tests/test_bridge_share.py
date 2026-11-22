"""ShareBridge.startShare's answer for a .torrent it can't add."""

from unittest.mock import MagicMock

from torrent2000.engine.session_manager import TorrentAlreadyPresentError
from torrent2000.i18n.translator import tr
from torrent2000.ui.web.bridge_share import ShareBridge


def test_a_torrent_file_that_cannot_be_added_says_why(tmp_path):
    """Every failure read "Ce torrent est déjà présent.", a corrupt file too."""
    session_manager = MagicMock()
    bridge = ShareBridge(session_manager, MagicMock(), MagicMock())
    answers = []
    for failure in (RuntimeError("expected value in bencoded string [bdecode:4]"), TorrentAlreadyPresentError("h1")):
        session_manager.add_torrent_from_file.side_effect = failure
        bridge.selectTorrentFile(str(tmp_path / "corrupt.torrent"))
        answers.append(bridge.startShare(str(tmp_path), "", 0, 0, 0.0))

    assert answers == [
        {"ok": False, "error": "expected value in bencoded string [bdecode:4]"},
        {"ok": False, "error": tr("add_tab.duplicate_message")},
    ]


def test_resuming_a_share_still_awaiting_analysis_starts_it():
    """Its ▶ only un-paused it: a magnet share CCCP had held stayed "awaiting
    analysis", in upload mode, whatever the theme since."""
    session_manager = MagicMock()
    bridge = ShareBridge(session_manager, MagicMock(), MagicMock())

    session_manager.get_record.return_value.awaiting_analysis = True
    bridge.resumeTorrent("held")
    session_manager.get_record.return_value.awaiting_analysis = False
    bridge.resumeTorrent("paused")

    session_manager.start_after_analysis.assert_called_once_with("held")
    session_manager.resume_torrent.assert_called_once_with("paused")
