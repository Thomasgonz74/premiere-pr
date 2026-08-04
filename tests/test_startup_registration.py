import winreg

import pytest

from torrent2000.engine import startup_registration as sr


@pytest.fixture(autouse=True)
def cleanup_registry_value():
    # Regardless of what a test does, never leave a real "launch at Windows
    # startup" entry behind in the developer's own registry.
    yield
    sr.set_launch_at_startup(False)


def test_disabled_by_default_on_a_clean_machine():
    sr.set_launch_at_startup(False)
    assert sr.is_launch_at_startup_enabled() is False


def test_enable_then_query_reports_enabled():
    sr.set_launch_at_startup(True)
    assert sr.is_launch_at_startup_enabled() is True


def test_disable_removes_the_value():
    sr.set_launch_at_startup(True)
    sr.set_launch_at_startup(False)
    assert sr.is_launch_at_startup_enabled() is False


def test_disabling_when_already_absent_does_not_raise():
    sr.set_launch_at_startup(False)
    sr.set_launch_at_startup(False)  # must not raise FileNotFoundError


def test_registered_command_actually_launches_this_interpreter():
    sr.set_launch_at_startup(True)
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, sr._RUN_KEY_PATH, 0, winreg.KEY_READ)
    try:
        value, _ = winreg.QueryValueEx(key, sr._VALUE_NAME)
    finally:
        winreg.CloseKey(key)
    assert value == sr._launch_command()
