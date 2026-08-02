"""Pure-logic tests for the CCCP theme's "no downloading, only sharing"
rule -- see engine/session_manager.py's _is_download_start_blocked, used by
add_torrent_from_file/start_after_analysis/resume_torrent to refuse
starting or resuming any torrent that isn't already 100% complete.
"""

from torrent2000.engine.session_manager import _is_download_start_blocked
from torrent2000.theme_ids import CCCP_THEME_ID


def test_not_blocked_under_any_non_cccp_theme():
    assert _is_download_start_blocked("luna_xp", progress=0.0) is False
    assert _is_download_start_blocked("macos_modern", progress=0.0) is False
    assert _is_download_start_blocked("win95_classic", progress=0.5) is False


def test_blocked_under_cccp_while_incomplete():
    assert _is_download_start_blocked(CCCP_THEME_ID, progress=0.0) is True
    assert _is_download_start_blocked(CCCP_THEME_ID, progress=0.99) is True


def test_not_blocked_under_cccp_once_fully_downloaded():
    # A finished torrent is pure seeding -- sharing is the whole point of
    # this theme, so resuming/re-seeding it is always allowed.
    assert _is_download_start_blocked(CCCP_THEME_ID, progress=1.0) is False
