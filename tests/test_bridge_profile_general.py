"""ProfileGeneralBridge.saveSettings: the launch-at-startup checkbox shows
the real HKCU Run key, so Save must compare against that, not against the
saved setting (registry functions stubbed, the real Run key is never touched)."""

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from torrent2000.config.settings import Settings
from torrent2000.ui.web import bridge_profile_general
from torrent2000.ui.web.bridge_profile_general import ProfileGeneralBridge


@pytest.mark.parametrize("saved, run_key", [(False, True), (True, False)])
def test_toggling_the_checkbox_rewrites_a_run_key_out_of_step_with_the_setting(tmp_path, monkeypatch, saved, run_key):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    registry = {"enabled": run_key}
    monkeypatch.setattr(bridge_profile_general.startup_registration, "is_launch_at_startup_enabled", lambda: registry["enabled"])
    monkeypatch.setattr(
        bridge_profile_general.startup_registration, "set_launch_at_startup", lambda on: registry.update(enabled=on)
    )
    settings = Settings()
    settings.launch_at_startup = saved
    bridge = ProfileGeneralBridge(session_manager=MagicMock(), settings=settings)

    shown = bridge.getLaunchAtStartupActual()
    bridge.saveSettings({"launchAtStartup": not shown})

    assert registry["enabled"] is (not run_key)
    assert settings.launch_at_startup is (not run_key)


def test_theme_names_follow_the_language():
    """"Soviétique productiviste (Constructivisme)" in every language."""
    import json
    from pathlib import Path

    from torrent2000.i18n import translator

    english = json.loads(
        (Path(__file__).resolve().parents[1] / "resources" / "i18n" / "en.json").read_text(encoding="utf-8")
    )
    translator.set_language("en")
    try:
        labels = {option["id"]: option["label"] for option in ProfileGeneralBridge(None, None).getThemeOptions()}
    finally:
        translator.set_language(translator.DEFAULT_LANGUAGE)

    assert labels["cccp_soviet"] == english["web.profile_general.theme_cccp_soviet"]
    assert labels["luna_xp"] == "Windows XP (Luna)"  # a proper name, as is
    assert not [label for label in labels.values() if label.startswith("web.")]


def test_save_applies_the_rate_limits_and_the_maximum_to_the_running_session(tmp_path, monkeypatch):
    """Only read when the session is built: "Paramètres enregistrés." and no
    effect until the next launch."""
    from PySide6.QtWidgets import QApplication

    from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
    from torrent2000.engine.session_manager import SessionManager

    QApplication.instance() or QApplication([])
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(bridge_profile_general.startup_registration, "is_launch_at_startup_enabled", lambda: False)
    settings = Settings()
    settings.network_interface = "127.0.0.1"
    session_manager = SessionManager(settings)
    try:
        bridge = ProfileGeneralBridge(
            session_manager, settings, bandwidth_scheduler=BandwidthScheduler(session_manager, settings)
        )

        bridge.saveSettings({"downloadRateLimitKbps": 50, "uploadRateLimitKbps": 20, "maxActiveDownloads": 2})

        live = session_manager._session.get_settings()
    finally:
        session_manager.shutdown(timeout_ms=0)

    assert (live["download_rate_limit"], live["upload_rate_limit"]) == (50 * 1024, 20 * 1024)
    assert (live["active_downloads"], live["active_seeds"]) == (2, 2)


def test_a_save_that_keeps_the_maximum_leaves_the_memory_governors_halving(tmp_path, monkeypatch):
    """Applied again in full by any Save (a webhook change...), while the
    governor, still throttling, never halved it again."""
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(bridge_profile_general.startup_registration, "is_launch_at_startup_enabled", lambda: False)
    session_manager = MagicMock()
    bridge = ProfileGeneralBridge(session_manager, Settings())

    bridge.saveSettings({"webhookEnabled": True, "maxActiveDownloads": Settings().max_active_downloads})
    session_manager.set_max_active_downloads.assert_not_called()
    bridge.saveSettings({"maxActiveDownloads": 3})
    session_manager.set_max_active_downloads.assert_called_once_with(3)
