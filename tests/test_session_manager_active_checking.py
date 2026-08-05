"""Regression guard for the "can't share two torrents at once" bug.

libtorrent's own default for "active_checking" is 1 -- only one
auto-managed torrent, session-wide, may occupy the "checking files" slot at
a time. Every torrent added via the Partage tab has to pass through that
check before it can seed, so a second share sat paused/stuck at 0% until the
first one's check finished. _build_session_settings must set this alongside
active_downloads/active_seeds, and set_max_active_downloads must keep it in
sync on live-apply.
"""

from unittest.mock import MagicMock

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager, _build_session_settings


def test_active_checking_matches_max_active_downloads():
    settings = Settings()
    settings.max_active_downloads = 5
    fragment = _build_session_settings(settings)
    assert fragment["active_checking"] == 5
    assert fragment["active_checking"] == fragment["active_downloads"] == fragment["active_seeds"]


def test_active_checking_scales_with_the_setting():
    settings = Settings()
    settings.max_active_downloads = 12
    fragment = _build_session_settings(settings)
    assert fragment["active_checking"] == 12


def test_set_max_active_downloads_keeps_active_checking_in_sync():
    session_manager = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    session_manager._session = MagicMock()

    session_manager.set_max_active_downloads(7)

    session_manager._session.apply_settings.assert_called_once_with(
        {
            "active_downloads": 7,
            "active_seeds": 7,
            "active_checking": 7,
            "active_limit": 14,
        }
    )
