"""Coverage for NetworkProfileStore (pure JSON persistence, mirrors
test_known_disk_service.py's isolated_data_dir pattern) and
NetworkProfileSwitcherService: opt-in (Settings.network_profile_auto_switch_
enabled, off by default), Windows netsh SSID parsing, and -- the point most
worth locking down -- that a matched SSID replays the FULL live-apply chain
(set_rate_limits/set_restrict_discovery/set_proxy/set_encryption_mode) on
top of apply_to_settings(), not apply_to_settings() alone. Skipping any one
of those calls would mean a profile switch silently never reaches the
running libtorrent session -- see bridge_profile_advanced.py's applyProfile,
which network_profile_switcher.py's _apply_profile must mirror exactly.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import network_profile_switcher as nps_module
from torrent2000.engine.network_profile_switcher import (
    NetworkProfileAssociation,
    NetworkProfileStore,
    NetworkProfileSwitcherService,
    get_current_ssid,
)
from torrent2000.engine.settings_profiles import SettingsProfile, SettingsProfileStore


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _settings(enabled: bool) -> Settings:
    settings = Settings()
    settings.network_profile_auto_switch_enabled = enabled
    return settings


class FakeSessionManager(QObject):
    def __init__(self):
        super().__init__()
        self.calls: list[str] = []

    def set_rate_limits(self, download_kbps, upload_kbps):
        self.calls.append(f"set_rate_limits({download_kbps},{upload_kbps})")

    def set_restrict_discovery(self, enabled):
        self.calls.append(f"set_restrict_discovery({enabled})")

    def set_proxy(self, settings):
        self.calls.append("set_proxy")

    def set_encryption_mode(self, mode):
        self.calls.append(f"set_encryption_mode({mode})")


def _profile(name="Public") -> SettingsProfile:
    return SettingsProfile(
        name=name,
        proxy_enabled=True,
        proxy_force=True,
        encryption_mode="forced",
        notifications_enabled=False,
        download_rate_limit_kbps=100,
        upload_rate_limit_kbps=50,
        restrict_discovery=True,
    )


# ----------------------------------------------------------------- NetworkProfileStore


def test_store_starts_empty_when_no_file_exists():
    assert NetworkProfileStore().list_associations() == []


def test_store_save_list_delete_roundtrip():
    store = NetworkProfileStore()
    store.save_association(NetworkProfileAssociation(ssid="HomeWifi", profile_name="Domicile"))
    assert [a.ssid for a in store.list_associations()] == ["HomeWifi"]

    reloaded = NetworkProfileStore()
    assert [(a.ssid, a.profile_name) for a in reloaded.list_associations()] == [("HomeWifi", "Domicile")]

    reloaded.delete("HomeWifi")
    assert reloaded.list_associations() == []
    assert NetworkProfileStore().list_associations() == []


def test_store_save_replaces_existing_entry_for_the_same_ssid():
    store = NetworkProfileStore()
    store.save_association(NetworkProfileAssociation(ssid="HomeWifi", profile_name="Old"))
    store.save_association(NetworkProfileAssociation(ssid="HomeWifi", profile_name="New"))
    associations = store.list_associations()
    assert len(associations) == 1
    assert associations[0].profile_name == "New"


# ------------------------------------------------------------------- get_current_ssid


def test_get_current_ssid_parses_netsh_output(monkeypatch):
    fake_stdout = (
        "There is 1 interface on the system:\n\n"
        "    Name                   : Wi-Fi\n"
        "    Description            : Some Adapter\n"
        "    State                  : connected\n"
        "    SSID                   : MyHomeNetwork\n"
        "    BSSID                  : 00:11:22:33:44:55\n"
    )
    monkeypatch.setattr(
        nps_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=fake_stdout, stderr=""),
    )
    assert get_current_ssid() == "MyHomeNetwork"


def test_get_current_ssid_none_when_not_connected(monkeypatch):
    fake_stdout = "There is 1 interface on the system:\n\n    Name : Wi-Fi\n    State : disconnected\n"
    monkeypatch.setattr(
        nps_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=fake_stdout, stderr=""),
    )
    assert get_current_ssid() is None


def test_get_current_ssid_none_on_missing_netsh(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("netsh not found")

    monkeypatch.setattr(nps_module.subprocess, "run", _raise)
    assert get_current_ssid() is None


def test_get_current_ssid_none_on_timeout(monkeypatch):
    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="netsh", timeout=5)

    monkeypatch.setattr(nps_module.subprocess, "run", _raise)
    assert get_current_ssid() is None


def test_get_current_ssid_none_on_nonzero_returncode(monkeypatch):
    monkeypatch.setattr(
        nps_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="error"),
    )
    assert get_current_ssid() is None


# --------------------------------------------------------- NetworkProfileSwitcherService


def test_disabled_by_default_never_applies(monkeypatch):
    monkeypatch.setattr(nps_module, "get_current_ssid", lambda: "PublicWifi")
    settings = _settings(enabled=False)
    store = NetworkProfileStore()
    store.save_association(NetworkProfileAssociation(ssid="PublicWifi", profile_name="Public"))
    profile_store = SettingsProfileStore()
    profile_store.save_from_settings("Public", _settings_from_profile(_profile("Public")))
    fake_sm = FakeSessionManager()

    service = NetworkProfileSwitcherService(fake_sm, settings, store, profile_store)
    service.check_now()

    assert fake_sm.calls == []


def test_matched_ssid_replays_the_full_live_apply_chain_not_just_apply_to_settings(monkeypatch):
    """The critical regression this feature must never reintroduce: applying
    a profile on SSID match has to touch the running session, not just the
    in-memory Settings object -- see module docstring."""
    monkeypatch.setattr(nps_module, "get_current_ssid", lambda: "PublicWifi")
    settings = _settings(enabled=True)
    settings.download_rate_limit_kbps = 0
    settings.restrict_discovery = False
    settings.encryption_mode = "enabled"

    store = NetworkProfileStore()
    store.save_association(NetworkProfileAssociation(ssid="PublicWifi", profile_name="Public"))

    profile_store = SettingsProfileStore()
    profile_store.save_from_settings("Public", _settings_from_profile(_profile("Public")))

    fake_sm = FakeSessionManager()
    service = NetworkProfileSwitcherService(fake_sm, settings, store, profile_store)

    service.check_now()

    # Settings itself was mutated (apply_to_settings ran)...
    assert settings.download_rate_limit_kbps == 100
    assert settings.restrict_discovery is True
    assert settings.encryption_mode == "forced"
    # ...AND every live-apply call the manual "Apply profile" bridge action
    # makes was replayed, in the same order, on the FakeSessionManager.
    assert fake_sm.calls == [
        "set_rate_limits(100,50)",
        "set_restrict_discovery(True)",
        "set_proxy",
        "set_encryption_mode(forced)",
    ]


def test_unregistered_ssid_never_applies(monkeypatch):
    monkeypatch.setattr(nps_module, "get_current_ssid", lambda: "SomeOtherWifi")
    settings = _settings(enabled=True)
    store = NetworkProfileStore()
    store.save_association(NetworkProfileAssociation(ssid="PublicWifi", profile_name="Public"))
    profile_store = SettingsProfileStore()
    fake_sm = FakeSessionManager()

    service = NetworkProfileSwitcherService(fake_sm, settings, store, profile_store)
    service.check_now()

    assert fake_sm.calls == []


def test_missing_profile_never_applies(monkeypatch):
    """Association points at a profile that was since renamed/deleted --
    must skip cleanly, never raise."""
    monkeypatch.setattr(nps_module, "get_current_ssid", lambda: "PublicWifi")
    settings = _settings(enabled=True)
    store = NetworkProfileStore()
    store.save_association(NetworkProfileAssociation(ssid="PublicWifi", profile_name="GoneProfile"))
    profile_store = SettingsProfileStore()  # no profiles registered
    fake_sm = FakeSessionManager()

    service = NetworkProfileSwitcherService(fake_sm, settings, store, profile_store)
    service.check_now()

    assert fake_sm.calls == []


def test_unchanged_ssid_does_not_reapply_every_tick(monkeypatch):
    monkeypatch.setattr(nps_module, "get_current_ssid", lambda: "PublicWifi")
    settings = _settings(enabled=True)
    store = NetworkProfileStore()
    store.save_association(NetworkProfileAssociation(ssid="PublicWifi", profile_name="Public"))
    profile_store = SettingsProfileStore()
    profile_store.save_from_settings("Public", _settings_from_profile(_profile("Public")))
    fake_sm = FakeSessionManager()

    service = NetworkProfileSwitcherService(fake_sm, settings, store, profile_store)
    service.check_now()
    assert len(fake_sm.calls) == 4

    fake_sm.calls.clear()
    service.check_now()  # same SSID again -- must not reapply
    assert fake_sm.calls == []


def test_no_ssid_is_a_noop(monkeypatch):
    monkeypatch.setattr(nps_module, "get_current_ssid", lambda: None)
    settings = _settings(enabled=True)
    store = NetworkProfileStore()
    profile_store = SettingsProfileStore()
    fake_sm = FakeSessionManager()

    service = NetworkProfileSwitcherService(fake_sm, settings, store, profile_store)
    service.check_now()

    assert fake_sm.calls == []


def _settings_from_profile(profile: SettingsProfile) -> Settings:
    """Builds a Settings object whose fields match `profile`, so
    save_from_settings() captures the exact values the test wants applied."""
    settings = Settings()
    settings.proxy.enabled = profile.proxy_enabled
    settings.proxy.force_proxy = profile.proxy_force
    settings.encryption_mode = profile.encryption_mode
    settings.notifications_enabled = profile.notifications_enabled
    settings.download_rate_limit_kbps = profile.download_rate_limit_kbps
    settings.upload_rate_limit_kbps = profile.upload_rate_limit_kbps
    settings.restrict_discovery = profile.restrict_discovery
    return settings
