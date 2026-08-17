"""Coverage for files_from_torrent_info's pad-file skipping and hidden/
executable flag reading, and files_from_torrent_path's disk-reading wrapper.

lt.torrent_info/file_storage is mocked directly (rather than built from a
real torrent) since only the plain flag bitwise-arithmetic in
files_from_torrent_info needs exercising; real int flag values are assigned
onto the mock so `flags & fs.flag_pad_file`-style checks behave exactly as
they would against the real libtorrent constants.
"""

from unittest.mock import MagicMock, patch

from torrent2000.danger_scanner.models import FileEntry
from torrent2000.engine.torrent_files import files_from_torrent_info, files_from_torrent_path

_FLAG_PAD_FILE = 1
_FLAG_HIDDEN = 2
_FLAG_EXECUTABLE = 4


def _mock_torrent_info(entries: list[tuple[str, int, int]]) -> MagicMock:
    """entries: list of (path, size, flags), flags built from the _FLAG_* constants above."""
    fs = MagicMock()
    fs.flag_pad_file = _FLAG_PAD_FILE
    fs.flag_hidden = _FLAG_HIDDEN
    fs.flag_executable = _FLAG_EXECUTABLE
    fs.num_files.return_value = len(entries)
    fs.file_path.side_effect = lambda i: entries[i][0]
    fs.file_size.side_effect = lambda i: entries[i][1]
    fs.file_flags.side_effect = lambda i: entries[i][2]
    ti = MagicMock()
    ti.files.return_value = fs
    return ti


def test_pad_files_are_skipped():
    ti = _mock_torrent_info(
        [
            ("real/file.txt", 100, 0),
            (".pad/1234", 924, _FLAG_PAD_FILE),
            ("other/file.bin", 50, 0),
        ]
    )

    result = files_from_torrent_info(ti)

    assert [f.path for f in result] == ["real/file.txt", "other/file.bin"]


def test_hidden_and_executable_flags_are_read():
    ti = _mock_torrent_info(
        [
            ("visible", 10, 0),
            (".hidden_file", 20, _FLAG_HIDDEN),
            ("run.sh", 30, _FLAG_EXECUTABLE),
            ("both", 40, _FLAG_HIDDEN | _FLAG_EXECUTABLE),
        ]
    )

    result = files_from_torrent_info(ti)

    assert [f.hidden for f in result] == [False, True, False, True]
    assert [f.executable_flag for f in result] == [False, False, True, True]


def test_index_and_size_are_preserved_across_a_skipped_pad_file():
    """The pad file at position 1 must not shift the index recorded for the
    file that follows it -- index tracks the original file_storage
    position, not the output list position."""
    ti = _mock_torrent_info(
        [
            ("a", 111, 0),
            ("pad", 5, _FLAG_PAD_FILE),
            ("b", 222, 0),
        ]
    )

    result = files_from_torrent_info(ti)

    assert result == [
        FileEntry(index=0, path="a", size=111, hidden=False, executable_flag=False),
        FileEntry(index=2, path="b", size=222, hidden=False, executable_flag=False),
    ]


def test_no_files_returns_empty_list():
    ti = _mock_torrent_info([])

    assert files_from_torrent_info(ti) == []


def test_files_from_torrent_path_constructs_torrent_info_from_disk_path():
    fake_ti = _mock_torrent_info([("only.txt", 5, 0)])

    with patch("torrent2000.engine.torrent_files.lt.torrent_info", return_value=fake_ti) as mock_ctor:
        result = files_from_torrent_path("C:/some/file.torrent")

    mock_ctor.assert_called_once_with("C:/some/file.torrent")
    assert result == [FileEntry(index=0, path="only.txt", size=5)]
