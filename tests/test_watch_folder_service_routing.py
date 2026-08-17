"""Integration coverage for WatchFolderService's routing-rule resolution
(see engine/routing_rules.py and scan_now's destination computation):
unlike the RSS/add-tab-magnet paths, the .torrent file is already fully on
disk here, so tracker-based rules must actually be usable, not just
name-based ones.
"""

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.routing_rules import RoutingRule, RoutingRuleStore
from torrent2000.engine.watch_folder_service import WatchFolderService


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path_factory.mktemp("data_dir")))


class FakeSessionManager:
    def __init__(self):
        self.added: list[tuple[str, str]] = []

    def add_torrent_from_file(self, path: str, save_path: str | None = None, excluded_indices=None) -> str:
        self.added.append((path, save_path))
        return "fakehash"


def _settings(watch_folder_path: str) -> Settings:
    settings = Settings()
    settings.watch_folder_enabled = True
    settings.watch_folder_path = watch_folder_path
    settings.default_download_dir = "C:/downloads"
    return settings


def _write_real_torrent(path, tracker_url: str = "http://tracker.example.com/announce") -> None:
    """Builds a real, parseable single-file .torrent (not just placeholder
    bytes) so lt.torrent_info(path).trackers() has something real to read --
    needed to exercise the tracker-matching branch, which the plain "fake
    torrent data" fixture used elsewhere in test_watch_folder_service.py
    can't (libtorrent can't parse that as a torrent at all)."""
    payload_dir = path.parent / f"{path.stem}_payload"
    payload_dir.mkdir(exist_ok=True)
    payload_path = payload_dir / "file.txt"
    payload_path.write_bytes(b"hello world")

    fs = lt.file_storage()
    lt.add_files(fs, str(payload_path))
    ct = lt.create_torrent(fs, 0, flags=lt.create_torrent.v1_only)
    ct.add_tracker(tracker_url)
    lt.set_piece_hashes(ct, str(payload_path.parent))
    path.write_bytes(lt.bencode(ct.generate()))


def test_tracker_rule_picks_the_matching_destination(tmp_path):
    RoutingRuleStore().save_rule(
        RoutingRule(name="private", pattern="tracker.example.com", match_field="tracker", destination="D:/private")
    )
    torrent_path = tmp_path / "a.torrent"
    _write_real_torrent(torrent_path, tracker_url="http://tracker.example.com/announce")
    settings = _settings(str(tmp_path))
    fake_sm = FakeSessionManager()
    service = WatchFolderService(fake_sm, settings)

    service.scan_now()

    assert fake_sm.added == [(str(torrent_path), "D:/private")]


def test_name_rule_picks_the_matching_destination_from_the_file_stem(tmp_path):
    RoutingRuleStore().save_rule(
        RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux")
    )
    torrent_path = tmp_path / "Ubuntu.24.04.torrent"
    _write_real_torrent(torrent_path)
    settings = _settings(str(tmp_path))
    fake_sm = FakeSessionManager()
    service = WatchFolderService(fake_sm, settings)

    service.scan_now()

    assert fake_sm.added == [(str(torrent_path), "D:/linux")]


def test_no_matching_rule_falls_back_to_default_download_dir(tmp_path):
    RoutingRuleStore().save_rule(
        RoutingRule(name="linux", pattern="fedora", match_field="name", destination="D:/linux")
    )
    torrent_path = tmp_path / "Ubuntu.24.04.torrent"
    _write_real_torrent(torrent_path, tracker_url="http://other.example.org/announce")
    settings = _settings(str(tmp_path))
    fake_sm = FakeSessionManager()
    service = WatchFolderService(fake_sm, settings)

    service.scan_now()

    assert fake_sm.added == [(str(torrent_path), "C:/downloads")]


def test_unparseable_torrent_file_falls_back_to_default_without_crashing(tmp_path):
    """The pre-existing "fake torrent data" fixture (see
    test_watch_folder_service.py) can't be parsed by libtorrent at all --
    _read_trackers must swallow that and treat it as "no tracker info",
    not raise and abort the whole scan."""
    RoutingRuleStore().save_rule(
        RoutingRule(name="linux", pattern="fedora", match_field="name", destination="D:/linux")
    )
    torrent_path = tmp_path / "a.torrent"
    torrent_path.write_bytes(b"not a real torrent file")
    settings = _settings(str(tmp_path))
    fake_sm = FakeSessionManager()
    service = WatchFolderService(fake_sm, settings)

    service.scan_now()  # must not raise

    assert fake_sm.added == [(str(torrent_path), "C:/downloads")]
