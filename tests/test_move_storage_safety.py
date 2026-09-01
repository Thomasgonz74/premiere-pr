"""Regression tests for SessionManager.is_safe_move_destination() -- defense
in depth for the moveStorage web bridge slot, which previously forwarded
any absolute path straight to libtorrent with zero validation. See
security_test/test_path_traversal.py and the published pentest report for
the original PoC (real downloaded files relocated outside the download
root via the bridge slot with no checks at all).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from torrent2000.engine.session_manager import is_safe_move_destination


def test_rejects_windows_system_directory():
    assert is_safe_move_destination(r"C:\Windows\System32") is False


def test_rejects_windows_root_directory():
    assert is_safe_move_destination(r"C:\Windows") is False


def test_rejects_program_files():
    assert is_safe_move_destination(r"C:\Program Files\SomeApp") is False


def test_rejects_program_files_x86():
    assert is_safe_move_destination(r"C:\Program Files (x86)\SomeApp") is False


def test_rejects_bare_drive_root():
    assert is_safe_move_destination("C:" + "\\") is False


def test_rejects_unc_network_path():
    assert is_safe_move_destination(r"\\attacker-server\share") is False


def test_allows_ordinary_user_chosen_folder(tmp_path):
    target = tmp_path / "MyTorrents"
    assert is_safe_move_destination(str(target)) is True


def test_allows_a_different_drive_letter(tmp_path):
    # tmp_path is already an absolute, ordinary path -- this just documents
    # that the check isn't hardcoded to a single drive letter.
    assert is_safe_move_destination(str(tmp_path)) is True


def test_rejects_unresolvable_path_instead_of_raising():
    # A path containing a null byte can't be resolved on Windows -- must
    # fail closed (reject), never raise past this function.
    assert is_safe_move_destination("C:\\Users\\bad\x00path") is False
