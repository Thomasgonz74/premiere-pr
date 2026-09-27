"""Coverage for torrent_creator.create_torrent_file: builds a real .torrent
via libtorrent and re-parses it with lt.torrent_info to confirm the output
is actually valid, not just "a file got written".
"""

import os
import threading

import libtorrent as lt
import pytest

from torrent2000.engine.torrent_creator import CreationCancelled, create_torrent_file


def _make_dir_source(tmp_path):
    source = tmp_path / "srcdir"
    source.mkdir()
    (source / "a.txt").write_bytes(b"A" * 20000)
    (source / "b.txt").write_bytes(b"B" * 5000)
    return source


def test_creates_valid_torrent_from_directory(tmp_path):
    source = _make_dir_source(tmp_path)
    output = tmp_path / "dir.torrent"

    create_torrent_file(str(source), str(output), trackers=[])

    ti = lt.torrent_info(str(output))
    assert ti.name() == "srcdir"
    assert ti.num_files() == 2
    assert not output.with_suffix(".torrent.tmp").exists()


def test_creates_valid_torrent_from_single_file(tmp_path):
    source = tmp_path / "single.bin"
    source.write_bytes(b"X" * 9999)
    output = tmp_path / "single.torrent"

    create_torrent_file(str(source), str(output), trackers=[])

    ti = lt.torrent_info(str(output))
    assert ti.name() == "single.bin"
    assert ti.num_files() == 1


def test_private_flag_is_set(tmp_path):
    source = _make_dir_source(tmp_path)
    output = tmp_path / "private.torrent"

    create_torrent_file(str(source), str(output), trackers=[], private=True)

    ti = lt.torrent_info(str(output))
    assert ti.priv() is True


def test_private_flag_defaults_to_false(tmp_path):
    source = _make_dir_source(tmp_path)
    output = tmp_path / "public.torrent"

    create_torrent_file(str(source), str(output), trackers=[])

    ti = lt.torrent_info(str(output))
    assert ti.priv() is False


def test_multiple_trackers_are_added(tmp_path):
    source = _make_dir_source(tmp_path)
    output = tmp_path / "trackers.torrent"
    trackers = ["http://tracker1.example.com/announce", "http://tracker2.example.com/announce"]

    create_torrent_file(str(source), str(output), trackers=trackers)

    ti = lt.torrent_info(str(output))
    # Not order-sensitive: libtorrent shuffles same-tier trackers on its own
    # (BEP 12 load-balancing) when it re-parses the generated torrent, so
    # only membership -- not position -- is guaranteed to survive round-trip.
    assert {t.url for t in ti.trackers()} == set(trackers)


def test_blank_trackers_are_skipped(tmp_path):
    source = _make_dir_source(tmp_path)
    output = tmp_path / "blank_trackers.torrent"

    create_torrent_file(str(source), str(output), trackers=["  ", "http://tracker.example.com/announce", ""])

    ti = lt.torrent_info(str(output))
    assert [t.url for t in ti.trackers()] == ["http://tracker.example.com/announce"]


def test_comment_is_set(tmp_path):
    source = _make_dir_source(tmp_path)
    output = tmp_path / "comment.torrent"

    create_torrent_file(str(source), str(output), trackers=[], comment="hello world")

    ti = lt.torrent_info(str(output))
    assert ti.comment() == "hello world"


def test_missing_source_raises_file_not_found(tmp_path):
    missing = tmp_path / "does_not_exist"
    output = tmp_path / "out.torrent"

    with pytest.raises(FileNotFoundError):
        create_torrent_file(str(missing), str(output), trackers=[])

    assert not output.exists()


def test_output_write_is_atomic_no_leftover_tmp_file(tmp_path):
    source = _make_dir_source(tmp_path)
    output = tmp_path / "atomic.torrent"

    create_torrent_file(str(source), str(output), trackers=[])

    assert output.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_piece_hashes_match_libtorrents_own(tmp_path):
    # Pieces straddling file boundaries, an empty file, a short last piece.
    source = tmp_path / "mixed"
    (source / "sub").mkdir(parents=True)
    (source / "a.bin").write_bytes(os.urandom(40000))
    (source / "empty.bin").write_bytes(b"")
    (source / "sub" / "c.bin").write_bytes(os.urandom(30001))
    output = tmp_path / "mixed.torrent"

    create_torrent_file(str(source), str(output), trackers=[])

    fs = lt.file_storage()
    lt.add_files(fs, str(source))
    ct = lt.create_torrent(fs, 0, flags=lt.create_torrent.v1_only)
    ct.set_creator("Torrent 2000")
    lt.set_piece_hashes(ct, str(tmp_path))
    expected = lt.torrent_info(lt.bencode(ct.generate()))
    assert lt.torrent_info(str(output)).info_hash() == expected.info_hash()


def test_cancel_stops_hashing_and_writes_nothing(tmp_path):
    source = _make_dir_source(tmp_path)
    output = tmp_path / "cancelled.torrent"
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(CreationCancelled):
        create_torrent_file(str(source), str(output), trackers=[], cancel=cancel)

    assert list(tmp_path.glob("cancelled.torrent*")) == []
