"""Coverage for KnownDiskStore (pure JSON persistence, mirrors
test_routing_rules.py's isolated_data_dir pattern) and KnownDiskService:
opt-in (Settings.known_disk_automation_enabled, off by default), matches by
volume LABEL (not mount point/drive letter), fires the confirmation signal
once per fresh insertion (not on every tick while still inserted), and never
executes anything -- it only ever emits diskConfirmationRequested. Mirrors
test_disk_reconnect_service.py's structure: get_volume_label monkeypatched
module-wide since real volume identity isn't what this test exercises."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections import namedtuple

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import known_disk_service as kds_module
from torrent2000.engine.known_disk_service import KnownDisk, KnownDiskService, KnownDiskStore

FakePartition = namedtuple("FakePartition", ["device", "mountpoint", "fstype", "opts"])


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _settings(enabled: bool) -> Settings:
    settings = Settings()
    settings.known_disk_automation_enabled = enabled
    return settings


# ----------------------------------------------------------------- KnownDiskStore


def test_store_starts_empty_when_no_file_exists():
    assert KnownDiskStore().list_disks() == []


def test_store_save_list_delete_roundtrip():
    store = KnownDiskStore()
    store.save_disk(KnownDisk(label="BACKUP_USB", action="copy to D:/Backups"))
    assert [d.label for d in store.list_disks()] == ["BACKUP_USB"]

    # Persisted -- a fresh store instance reads the same file back.
    reloaded = KnownDiskStore()
    assert [(d.label, d.action) for d in reloaded.list_disks()] == [("BACKUP_USB", "copy to D:/Backups")]

    reloaded.delete("BACKUP_USB")
    assert reloaded.list_disks() == []
    assert KnownDiskStore().list_disks() == []


def test_store_save_replaces_existing_entry_for_the_same_label():
    store = KnownDiskStore()
    store.save_disk(KnownDisk(label="BACKUP_USB", action="old action"))
    store.save_disk(KnownDisk(label="BACKUP_USB", action="new action"))
    disks = store.list_disks()
    assert len(disks) == 1
    assert disks[0].action == "new action"


# --------------------------------------------------------------- KnownDiskService


def test_disabled_by_default_never_emits(monkeypatch):
    monkeypatch.setattr(kds_module.psutil, "disk_partitions", lambda: [FakePartition("E:", "E:\\", "NTFS", "")])
    monkeypatch.setattr(kds_module, "get_volume_label", lambda path: "BACKUP_USB")

    store = KnownDiskStore()
    store.save_disk(KnownDisk(label="BACKUP_USB", action="copy to D:/Backups"))
    service = KnownDiskService(store, _settings(enabled=False))

    received = []
    service.diskConfirmationRequested.connect(lambda info, action: received.append((info, action)))
    service.check_now()

    assert received == []


def test_emits_once_when_a_known_label_appears_on_a_new_mountpoint(monkeypatch):
    monkeypatch.setattr(kds_module.psutil, "disk_partitions", lambda: [])
    store = KnownDiskStore()
    store.save_disk(KnownDisk(label="BACKUP_USB", action="copy to D:/Backups"))
    service = KnownDiskService(store, _settings(enabled=True))

    received = []
    service.diskConfirmationRequested.connect(lambda info, action: received.append((info, action)))

    # Nothing mounted yet.
    service.check_now()
    assert received == []

    # Disk appears.
    monkeypatch.setattr(kds_module.psutil, "disk_partitions", lambda: [FakePartition("E:", "E:\\", "NTFS", "")])
    monkeypatch.setattr(kds_module, "get_volume_label", lambda path: "BACKUP_USB")
    service.check_now()
    assert len(received) == 1
    info, action = received[0]
    assert '"label": "BACKUP_USB"' in info
    assert '"mountpoint": "E:\\\\"' in info
    assert action == "copy to D:/Backups"

    # Still inserted on the next tick -- must not refire.
    service.check_now()
    assert len(received) == 1


def test_unregistered_label_never_emits(monkeypatch):
    monkeypatch.setattr(kds_module.psutil, "disk_partitions", lambda: [FakePartition("E:", "E:\\", "NTFS", "")])
    monkeypatch.setattr(kds_module, "get_volume_label", lambda path: "SOME_OTHER_DISK")
    store = KnownDiskStore()
    store.save_disk(KnownDisk(label="BACKUP_USB", action="copy to D:/Backups"))
    service = KnownDiskService(store, _settings(enabled=True))

    received = []
    service.diskConfirmationRequested.connect(lambda info, action: received.append((info, action)))
    service.check_now()

    assert received == []


def test_a_disk_already_present_before_enabling_does_not_retroactively_fire(monkeypatch):
    """Mirrors DiskReconnectService's "don't fire the instant it's first
    checked" concern -- a known disk that was already mounted while the
    feature was off must not be treated as "just inserted" the moment the
    user later enables it."""
    monkeypatch.setattr(kds_module.psutil, "disk_partitions", lambda: [FakePartition("E:", "E:\\", "NTFS", "")])
    monkeypatch.setattr(kds_module, "get_volume_label", lambda path: "BACKUP_USB")
    store = KnownDiskStore()
    store.save_disk(KnownDisk(label="BACKUP_USB", action="copy to D:/Backups"))
    settings = _settings(enabled=False)
    service = KnownDiskService(store, settings)

    received = []
    service.diskConfirmationRequested.connect(lambda info, action: received.append((info, action)))

    service.check_now()  # disabled -- but E:\ gets tracked as already-seen
    assert received == []

    settings.known_disk_automation_enabled = True
    service.check_now()  # same still-mounted disk -- must not fire now either
    assert received == []
