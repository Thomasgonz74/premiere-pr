"""Covers integration of the four "differentiator" sections (Security
Center, Settings Profiles, Remote Access, Routing Rules) into ProfileTab:
they're instantiated and exposed as attributes, included in self._sections
so Save persists them, and wired into ProfileTab.retranslate_ui()."""

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.tabs.profile_tab import ProfileTab
from torrent2000.ui.widgets.remote_access_section import RemoteAccessSection
from torrent2000.ui.widgets.routing_rules_section import RoutingRulesSection
from torrent2000.ui.widgets.security_center_section import SecurityCenterSection
from torrent2000.ui.widgets.settings_profiles_section import SettingsProfilesSection


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    # RoutingRulesSection (like SettingsProfilesSection) owns a store that
    # reads/writes under the app-data directory -- isolate it so this file
    # never touches (or creates) the real %APPDATA%/Torrent2000 folder.
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


@pytest.fixture
def tab():
    settings = Settings()
    settings.save = MagicMock()  # avoid touching the real config file on disk
    widget = ProfileTab(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings, MagicMock())
    yield widget, settings


# --------------------------------------------------------------- instantiation


def test_security_center_section_is_instantiated_and_exposed(tab):
    widget, _ = tab
    assert isinstance(widget.security_center_section, SecurityCenterSection)


def test_settings_profiles_section_is_instantiated_and_exposed(tab):
    widget, _ = tab
    assert isinstance(widget.settings_profiles_section, SettingsProfilesSection)


def test_remote_access_section_is_instantiated_and_exposed(tab):
    widget, _ = tab
    assert isinstance(widget.remote_access_section, RemoteAccessSection)


def test_routing_rules_section_is_instantiated_and_exposed(tab):
    widget, _ = tab
    assert isinstance(widget.routing_rules_section, RoutingRulesSection)


# ------------------------------------------------------------- save wiring


def test_new_sections_are_registered_in_sections_list(tab):
    widget, _ = tab
    assert widget.security_center_section in widget._sections
    assert widget.settings_profiles_section in widget._sections
    assert widget.remote_access_section in widget._sections
    assert widget.routing_rules_section in widget._sections


def test_save_button_calls_write_to_on_each_new_section(tab):
    widget, settings = tab
    widget.security_center_section.write_to = MagicMock()
    widget.settings_profiles_section.write_to = MagicMock()
    widget.remote_access_section.write_to = MagicMock()
    widget.routing_rules_section.write_to = MagicMock()

    widget._on_save_clicked()

    widget.security_center_section.write_to.assert_called_once_with(settings)
    widget.settings_profiles_section.write_to.assert_called_once_with(settings)
    widget.remote_access_section.write_to.assert_called_once_with(settings)
    widget.routing_rules_section.write_to.assert_called_once_with(settings)


# ------------------------------------------------------------- retranslation


def test_retranslate_ui_calls_retranslate_on_each_new_section_without_raising(tab):
    widget, _ = tab
    widget.security_center_section.retranslate_ui = MagicMock()
    widget.settings_profiles_section.retranslate_ui = MagicMock()
    widget.remote_access_section.retranslate_ui = MagicMock()
    widget.routing_rules_section.retranslate_ui = MagicMock()

    widget.retranslate_ui()  # must not raise

    widget.security_center_section.retranslate_ui.assert_called_once()
    widget.settings_profiles_section.retranslate_ui.assert_called_once()
    widget.remote_access_section.retranslate_ui.assert_called_once()
    widget.routing_rules_section.retranslate_ui.assert_called_once()


def test_retranslate_ui_does_not_raise_with_real_new_sections(tab):
    widget, _ = tab
    widget.retranslate_ui()  # must not raise using the real (non-mocked) sections
