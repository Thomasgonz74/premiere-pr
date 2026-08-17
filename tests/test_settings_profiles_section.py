import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from torrent2000.config.settings import Settings
from torrent2000.engine.settings_profiles import SettingsProfileStore
from torrent2000.ui.widgets.settings_profiles_section import SettingsProfilesSection


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _saved_travel_profile() -> None:
    settings = Settings()
    settings.proxy.enabled = True
    settings.proxy.force_proxy = True
    settings.encryption_mode = "forced"
    settings.notifications_enabled = False
    settings.download_rate_limit_kbps = 200
    settings.upload_rate_limit_kbps = 50
    settings.restrict_discovery = True
    SettingsProfileStore().save_from_settings("voyage", settings)


def test_apply_button_calls_the_four_session_manager_methods_with_profile_values():
    _saved_travel_profile()
    settings = Settings()  # defaults, distinct from the saved profile
    settings.save = MagicMock()
    session_manager = MagicMock()

    section = SettingsProfilesSection(settings, session_manager)
    idx = section.profile_combo.findData("voyage")
    assert idx >= 0
    section.profile_combo.setCurrentIndex(idx)

    section._on_apply_clicked()

    session_manager.set_rate_limits.assert_called_once_with(200, 50)
    session_manager.set_restrict_discovery.assert_called_once_with(True)
    session_manager.set_proxy.assert_called_once_with(settings)
    session_manager.set_encryption_mode.assert_called_once_with("forced")
    settings.save.assert_called_once()

    # The 4 calls must reflect settings *after* the profile was applied.
    assert settings.proxy.enabled is True
    assert settings.proxy.force_proxy is True
    assert settings.notifications_enabled is False


def test_apply_button_does_nothing_when_no_profile_exists():
    settings = Settings()
    settings.save = MagicMock()
    session_manager = MagicMock()

    section = SettingsProfilesSection(settings, session_manager)
    section._on_apply_clicked()

    session_manager.set_rate_limits.assert_not_called()
    session_manager.set_restrict_discovery.assert_not_called()
    session_manager.set_proxy.assert_not_called()
    session_manager.set_encryption_mode.assert_not_called()
    settings.save.assert_not_called()


def test_save_as_creates_a_profile_from_current_settings(monkeypatch):
    settings = Settings()
    settings.download_rate_limit_kbps = 77
    session_manager = MagicMock()
    section = SettingsProfilesSection(settings, session_manager)

    monkeypatch.setattr("torrent2000.ui.widgets.settings_profiles_section.QInputDialog.getText", lambda *a, **k: ("mobile", True))

    section._on_save_as_clicked()

    names = [p.name for p in section._store.list_profiles()]
    assert names == ["mobile"]
    assert section.profile_combo.findData("mobile") >= 0


def test_save_as_cancelled_dialog_creates_no_profile(monkeypatch):
    settings = Settings()
    session_manager = MagicMock()
    section = SettingsProfilesSection(settings, session_manager)

    monkeypatch.setattr("torrent2000.ui.widgets.settings_profiles_section.QInputDialog.getText", lambda *a, **k: ("", False))

    section._on_save_as_clicked()

    assert section._store.list_profiles() == []


def test_delete_button_removes_profile_after_confirmation(monkeypatch):
    _saved_travel_profile()
    settings = Settings()
    session_manager = MagicMock()
    section = SettingsProfilesSection(settings, session_manager)
    idx = section.profile_combo.findData("voyage")
    section.profile_combo.setCurrentIndex(idx)

    monkeypatch.setattr(
        "torrent2000.ui.widgets.settings_profiles_section.QMessageBox.question",
        lambda *a, **k: QMessageBox.Yes,
    )

    section._on_delete_clicked()

    assert section._store.list_profiles() == []
    assert section.profile_combo.count() == 0


def test_delete_button_declined_confirmation_keeps_profile(monkeypatch):
    _saved_travel_profile()
    settings = Settings()
    session_manager = MagicMock()
    section = SettingsProfilesSection(settings, session_manager)
    idx = section.profile_combo.findData("voyage")
    section.profile_combo.setCurrentIndex(idx)

    monkeypatch.setattr(
        "torrent2000.ui.widgets.settings_profiles_section.QMessageBox.question",
        lambda *a, **k: QMessageBox.No,
    )

    section._on_delete_clicked()

    assert [p.name for p in section._store.list_profiles()] == ["voyage"]


def test_write_to_does_nothing():
    settings = Settings()
    session_manager = MagicMock()
    section = SettingsProfilesSection(settings, session_manager)
    other_settings = Settings()
    other_settings.download_rate_limit_kbps = 999

    section.write_to(other_settings)

    assert other_settings.download_rate_limit_kbps == 999  # unchanged
