import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from torrent2000.config.settings import Settings
from torrent2000.engine.settings_profiles import SettingsProfile, SettingsProfileStore


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _settings_for_travel() -> Settings:
    settings = Settings()
    settings.proxy.enabled = True
    settings.proxy.force_proxy = True
    settings.encryption_mode = "forced"
    settings.notifications_enabled = False
    settings.download_rate_limit_kbps = 200
    settings.upload_rate_limit_kbps = 50
    settings.restrict_discovery = True
    return settings


def test_save_from_settings_then_list_round_trips_all_seven_fields():
    store = SettingsProfileStore()
    store.save_from_settings("voyage", _settings_for_travel())

    profiles = store.list_profiles()

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile == SettingsProfile(
        name="voyage",
        proxy_enabled=True,
        proxy_force=True,
        encryption_mode="forced",
        notifications_enabled=False,
        download_rate_limit_kbps=200,
        upload_rate_limit_kbps=50,
        restrict_discovery=True,
    )


def test_apply_to_settings_mutates_the_given_settings_in_place():
    store = SettingsProfileStore()
    store.save_from_settings("voyage", _settings_for_travel())
    profile = store.list_profiles()[0]

    target = Settings()  # defaults differ from the saved profile
    store.apply_to_settings(profile, target)

    assert target.proxy.enabled is True
    assert target.proxy.force_proxy is True
    assert target.encryption_mode == "forced"
    assert target.notifications_enabled is False
    assert target.download_rate_limit_kbps == 200
    assert target.upload_rate_limit_kbps == 50
    assert target.restrict_discovery is True


def test_delete_removes_the_named_profile():
    store = SettingsProfileStore()
    store.save_from_settings("voyage", _settings_for_travel())
    store.save_from_settings("mobile", Settings())

    store.delete("voyage")

    names = [p.name for p in store.list_profiles()]
    assert names == ["mobile"]


def test_persists_across_a_fresh_store_instance():
    store = SettingsProfileStore()
    store.save_from_settings("voyage", _settings_for_travel())

    reloaded = SettingsProfileStore()

    assert [p.name for p in reloaded.list_profiles()] == ["voyage"]
    assert reloaded.list_profiles()[0].download_rate_limit_kbps == 200


def test_delete_persists_across_a_fresh_store_instance():
    store = SettingsProfileStore()
    store.save_from_settings("voyage", _settings_for_travel())
    store.delete("voyage")

    reloaded = SettingsProfileStore()

    assert reloaded.list_profiles() == []


def test_saving_a_profile_of_the_same_name_replaces_it():
    store = SettingsProfileStore()
    store.save_from_settings("voyage", Settings())

    replacement = _settings_for_travel()
    store.save_from_settings("voyage", replacement)

    profiles = store.list_profiles()
    assert len(profiles) == 1
    assert profiles[0].download_rate_limit_kbps == 200
    assert profiles[0].encryption_mode == "forced"


def test_missing_persistence_file_starts_empty():
    store = SettingsProfileStore()
    assert store.list_profiles() == []


def test_corrupt_persistence_file_does_not_crash_startup():
    from torrent2000.config.paths import get_settings_profiles_path

    get_settings_profiles_path().write_text("not valid json {{{", encoding="utf-8")

    store = SettingsProfileStore()  # must not raise

    assert store.list_profiles() == []


def test_persistence_file_with_wrong_top_level_shape_does_not_crash_startup():
    from torrent2000.config.paths import get_settings_profiles_path

    get_settings_profiles_path().write_text('{"not": "a list"}', encoding="utf-8")

    store = SettingsProfileStore()  # must not raise

    assert store.list_profiles() == []


def test_persistence_file_with_malformed_entry_skips_it_without_crashing():
    import json

    from torrent2000.config.paths import get_settings_profiles_path

    get_settings_profiles_path().write_text(json.dumps([{"name": "broken"}]), encoding="utf-8")

    store = SettingsProfileStore()  # missing required fields -- must not raise

    assert store.list_profiles() == []
