"""Coverage for TagService: multiple free-form tags per torrent, persisted
the same way as engine/torrent_categories.py (see engine/tag_service.py)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import logging

import pytest

from torrent2000.config.paths import get_resume_dir, get_tags_path
from torrent2000.engine.tag_service import TagService


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def test_unknown_torrent_has_no_tags():
    service = TagService()
    assert service.get("hash1") == []


def test_add_then_get_round_trips():
    service = TagService()
    service.add("hash1", "linux")
    assert service.get("hash1") == ["linux"]


def test_adding_the_same_tag_twice_is_idempotent():
    service = TagService()
    service.add("hash1", "linux")
    service.add("hash1", "linux")
    assert service.get("hash1") == ["linux"]


def test_adding_an_empty_or_blank_tag_is_a_noop():
    service = TagService()
    service.add("hash1", "")
    service.add("hash1", "   ")
    assert service.get("hash1") == []


def test_multiple_tags_preserve_insertion_order():
    service = TagService()
    service.add("hash1", "linux")
    service.add("hash1", "iso")
    assert service.get("hash1") == ["linux", "iso"]


def test_remove_drops_just_that_tag():
    service = TagService()
    service.add("hash1", "linux")
    service.add("hash1", "iso")
    service.remove("hash1", "linux")
    assert service.get("hash1") == ["iso"]


def test_remove_last_tag_clears_the_torrent_entirely():
    service = TagService()
    service.add("hash1", "linux")
    service.remove("hash1", "linux")
    assert service.get("hash1") == []
    assert service.all_tags() == []


def test_remove_unknown_tag_is_a_noop():
    service = TagService()
    service.add("hash1", "linux")
    service.remove("hash1", "nope")
    assert service.get("hash1") == ["linux"]


def test_all_tags_is_sorted_and_deduplicated_across_torrents():
    service = TagService()
    service.add("hash1", "linux")
    service.add("hash2", "iso")
    service.add("hash2", "linux")
    assert service.all_tags() == ["iso", "linux"]


def test_clear_removes_every_tag_for_a_torrent():
    service = TagService()
    service.add("hash1", "linux")
    service.add("hash1", "iso")
    service.clear("hash1")
    assert service.get("hash1") == []


def test_persists_across_a_fresh_instance():
    service = TagService()
    service.add("hash1", "linux")

    reloaded = TagService()
    assert reloaded.get("hash1") == ["linux"]


def test_missing_persistence_file_starts_empty():
    service = TagService()  # must not raise
    assert service.all_tags() == []


def test_corrupt_persistence_file_does_not_crash_startup():
    get_tags_path().parent.mkdir(parents=True, exist_ok=True)
    get_tags_path().write_text("not valid json{{{", encoding="utf-8")

    service = TagService()  # must not raise

    assert service.all_tags() == []


def test_persistence_file_with_wrong_shape_entries_are_skipped():
    get_tags_path().parent.mkdir(parents=True, exist_ok=True)
    get_tags_path().write_text(json.dumps({"hash1": "not-a-list", "hash2": ["ok"]}), encoding="utf-8")

    service = TagService()

    assert service.get("hash1") == []
    assert service.get("hash2") == ["ok"]


def test_startup_drops_tags_of_torrents_without_a_resume_file(caplog):
    """Tags of torrents removed before removal purged them linger in
    tags.json. Kept: any torrent with a resume file, even one whose restore
    failed this time (not in memory), so its tags survive a missing disk."""
    service = TagService()
    service.add("kept", "linux")
    service.add("gone1", "iso")
    service.add("gone2", "iso")
    (get_resume_dir() / "kept.fastresume").write_bytes(b"")

    with caplog.at_level(logging.INFO, logger="torrent2000.engine.tag_service"):
        dropped = service.drop_orphans()

    assert dropped == 2
    assert TagService().all_tags() == ["linux"]  # persisted
    assert "dropped 2 entries" in caplog.text
    assert service.drop_orphans() == 0
