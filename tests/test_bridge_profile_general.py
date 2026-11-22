"""ProfileGeneralBridge.saveSettings: the launch-at-startup checkbox shows
the real HKCU Run key, so Save must compare against that, not against the
saved setting (registry functions stubbed, the real Run key is never touched)."""

import os

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
    bridge = ProfileGeneralBridge(session_manager=None, settings=settings)

    shown = bridge.getLaunchAtStartupActual()
    bridge.saveSettings({"launchAtStartup": not shown})

    assert registry["enabled"] is (not run_key)
    assert settings.launch_at_startup is (not run_key)
