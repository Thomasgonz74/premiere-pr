import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.watch_folder_service import WatchFolderService


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    # WatchFolderService now also owns a RoutingRuleStore (see
    # engine/routing_rules.py) which reads/writes under the app-data
    # directory -- isolate it so these tests never touch (or create) the
    # real %APPDATA%/Torrent2000 folder on the machine running them. A
    # dedicated tmp dir (not the per-test `tmp_path` already used below for
    # the watch folder itself) keeps the two concerns clearly separate.
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path_factory.mktemp("data_dir")))


class FakeSessionManager:
    def __init__(self):
        self.added: list[tuple[str, str]] = []

    def add_torrent_from_file(self, path: str, save_path: str | None = None, excluded_indices=None) -> str:
        self.added.append((path, save_path))
        return "fakehash"


def _settings(watch_folder_path: str, enabled: bool = True) -> Settings:
    settings = Settings()
    settings.watch_folder_enabled = enabled
    settings.watch_folder_path = watch_folder_path
    settings.default_download_dir = "C:/downloads"
    return settings


def test_disabled_service_does_not_scan(tmp_path):
    (tmp_path / "a.torrent").write_bytes(b"fake torrent data")
    settings = _settings(str(tmp_path), enabled=False)
    fake_sm = FakeSessionManager()
    service = WatchFolderService(fake_sm, settings)

    service.scan_now()

    assert fake_sm.added == []
    assert (tmp_path / "a.torrent").exists()


def test_adds_new_torrent_and_moves_it_to_processed(tmp_path):
    torrent_file = tmp_path / "a.torrent"
    torrent_file.write_bytes(b"fake torrent data")
    settings = _settings(str(tmp_path))
    fake_sm = FakeSessionManager()
    service = WatchFolderService(fake_sm, settings)

    service.scan_now()

    assert fake_sm.added == [(str(torrent_file), "C:/downloads")]
    assert not torrent_file.exists()
    assert (tmp_path / "processed" / "a.torrent").exists()


def test_processed_file_is_never_re_added(tmp_path):
    (tmp_path / "a.torrent").write_bytes(b"fake torrent data")
    settings = _settings(str(tmp_path))
    fake_sm = FakeSessionManager()
    service = WatchFolderService(fake_sm, settings)

    service.scan_now()
    service.scan_now()

    assert len(fake_sm.added) == 1


def test_missing_folder_is_a_no_op(tmp_path):
    settings = _settings(str(tmp_path / "does_not_exist"))
    fake_sm = FakeSessionManager()
    service = WatchFolderService(fake_sm, settings)

    service.scan_now()  # must not raise

    assert fake_sm.added == []


class FailingSessionManager:
    """Mirrors what the real SessionManager does on a duplicate info-hash or
    a corrupt/unparsable .torrent: add_torrent_from_file() raises. The plain
    FakeSessionManager above never raises, so it can't exercise this path."""

    def __init__(self):
        self.add_calls = 0

    def add_torrent_from_file(self, path: str, save_path: str | None = None, excluded_indices=None) -> str:
        self.add_calls += 1
        raise RuntimeError("torrent already exists in session")


def test_permanently_failing_torrent_is_quarantined_not_retried_forever(tmp_path):
    torrent_file = tmp_path / "dup.torrent"
    torrent_file.write_bytes(b"fake torrent data")
    settings = _settings(str(tmp_path))
    failing_sm = FailingSessionManager()
    service = WatchFolderService(failing_sm, settings)

    service.scan_now()
    service.scan_now()
    service.scan_now()

    # Retried once, then quarantined -- not retried on every subsequent scan.
    assert failing_sm.add_calls == 1
    assert not torrent_file.exists()
    assert (tmp_path / "failed" / "dup.torrent").exists()
