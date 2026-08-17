import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.widgets.remote_access_section import RemoteAccessSection


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _section(settings=None, session_manager=None):
    settings = settings or Settings()
    session_manager = session_manager or MagicMock()
    section = RemoteAccessSection(settings, session_manager)
    section._server.start = MagicMock()
    section._server.stop = MagicMock()
    return section, settings


def test_checking_the_box_starts_the_section_own_server():
    section, _ = _section()
    section.enabled_checkbox.setChecked(True)
    section._server.start.assert_called_once()
    section._server.stop.assert_not_called()


def test_checking_the_box_when_bind_fails_reverts_checkbox_and_clears_display():
    # Regression test: RemoteAccessServer.start() provisions+saves a token
    # BEFORE attempting the socket bind, so a bind failure (port already in
    # use, no permission, ...) must not be allowed to leave the UI showing a
    # fully "active"-looking token/URL for a server that never actually
    # started listening (section._server.is_running stays False).
    settings = Settings()
    session_manager = MagicMock()
    section = RemoteAccessSection(settings, session_manager)
    section._server.start = MagicMock(return_value=False)
    section._server.stop = MagicMock()

    # QMessageBox.warning() opens a real (blocking) modal dialog -- patch it
    # out, same as any other side-effecting Qt static call under test.
    with patch("torrent2000.ui.widgets.remote_access_section.QMessageBox.warning") as warning:
        section.enabled_checkbox.setChecked(True)

    warning.assert_called_once()
    assert section.enabled_checkbox.isChecked() is False
    assert not section._server.is_running
    assert section.token_input.text() == ""
    assert settings.remote_access_token == ""
    assert not section.copy_token_button.isEnabled()
    assert not section.copy_url_button.isEnabled()
    assert not section.reveal_token_button.isEnabled()


def test_unchecking_the_box_stops_the_section_own_server_and_clears_the_shared_token():
    # Regression test: the section owns its OWN RemoteAccessServer instance,
    # separate from app.py's boot-time one (see engine/remote_server.py's
    # module docstring) -- normally app.py's instance is the one actually
    # holding the socket, so calling .stop() on this section's own (never-
    # started) instance alone would silently do nothing, leaving the real
    # server listening with the still-valid token while the checkbox reads
    # "off". Clearing settings.remote_access_token must happen too, since
    # every server instance reads it fresh per request off the same shared
    # Settings object.
    settings = Settings()
    settings.remote_access_token = "some-real-token"
    section, settings = _section(settings)

    section.enabled_checkbox.setChecked(True)
    section.enabled_checkbox.setChecked(False)

    section._server.stop.assert_called_once()
    assert settings.remote_access_token == ""


def test_unchecking_when_no_token_was_ever_provisioned_does_not_touch_settings_save():
    settings = Settings()
    settings.save = MagicMock()
    section, settings = _section(settings)
    assert settings.remote_access_token == ""

    section.enabled_checkbox.setChecked(True)
    section.enabled_checkbox.setChecked(False)

    settings.save.assert_not_called()


def test_refresh_display_shows_not_started_yet_when_token_is_empty():
    section, _ = _section()
    assert section.token_input.text() == ""
    assert section.url_input.text() == section.url_input.text()  # no crash
    assert not section.copy_token_button.isEnabled()
    assert not section.reveal_token_button.isEnabled()


def test_regenerate_token_persists_and_refreshes_display():
    settings = Settings()
    settings.remote_access_token = "old-token"
    section, settings = _section(settings)

    section._on_regenerate_token()

    assert settings.remote_access_token != "old-token"
    assert settings.remote_access_token != ""
    assert section.token_input.text() == settings.remote_access_token


def test_write_to_persists_enabled_and_port_only():
    section, _ = _section()
    section.enabled_checkbox.setChecked(True)
    section._server.start.assert_called_once()
    section.port_spin.setValue(9001)

    other_settings = Settings()
    section.write_to(other_settings)

    assert other_settings.remote_access_enabled is True
    assert other_settings.remote_access_port == 9001
