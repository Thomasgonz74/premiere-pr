import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.watch_folder_service import WatchFolderService


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


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
