"""Round-trip coverage for resume-data persistence: save/load/delete against
a tmp_path-backed data dir, and the corrupt-file-is-skipped-not-crashed
behavior of load_all_resume_params."""

import libtorrent as lt
import pytest

from torrent2000.engine import persistence
from torrent2000.engine.persistence import (
    delete_resume_file,
    load_all_resume_params,
    resume_file_path,
    save_resume_params,
)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _params(save_path: str, name: str) -> "lt.add_torrent_params":
    p = lt.add_torrent_params()
    p.save_path = save_path
    p.name = name
    return p


def test_save_then_load_round_trips_resume_params():
    save_resume_params("hash1", _params("D:/downloads", "my-torrent"))

    loaded = load_all_resume_params()

    assert len(loaded) == 1
    assert loaded[0].save_path == "D:/downloads"
    assert loaded[0].name == "my-torrent"


def test_save_writes_to_the_expected_fastresume_path(tmp_path):
    save_resume_params("hash1", _params("D:/downloads", "my-torrent"))

    path = resume_file_path("hash1")

    assert path.exists()
    assert path.name == "hash1.fastresume"
    assert path.parent == persistence.get_resume_dir()


def test_load_all_resume_params_returns_empty_list_when_dir_has_no_files():
    assert load_all_resume_params() == []


def test_load_all_resume_params_skips_a_corrupt_file_without_crashing():
    save_resume_params("good", _params("D:/downloads", "good-torrent"))
    corrupt_path = resume_file_path("bad")
    corrupt_path.write_bytes(b"not valid bencoded resume data")

    loaded = load_all_resume_params()

    assert len(loaded) == 1
    assert loaded[0].name == "good-torrent"


def test_delete_resume_file_removes_an_existing_file():
    save_resume_params("hash1", _params("D:/downloads", "my-torrent"))
    path = resume_file_path("hash1")
    assert path.exists()

    delete_resume_file("hash1")

    assert not path.exists()


def test_delete_resume_file_missing_file_is_a_no_op():
    delete_resume_file("never-saved")  # must not raise


def test_save_overwrites_an_existing_resume_file_for_the_same_hash():
    save_resume_params("hash1", _params("D:/first", "first-name"))
    save_resume_params("hash1", _params("D:/second", "second-name"))

    loaded = load_all_resume_params()

    assert len(loaded) == 1
    assert loaded[0].name == "second-name"
    assert loaded[0].save_path == "D:/second"
