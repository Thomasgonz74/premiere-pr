import winreg

import pytest

from torrent2000.engine import startup_registration as sr

# Throwaway subkey under HKCU, isolated from the real
# Software\Microsoft\Windows\CurrentVersion\Run key that startup_registration
# touches by default -- these tests must never read/write the developer's
# actual Windows startup entry.
_TEST_ROOT_KEY_PATH = r"Software\Torrent2000_test_isolated"
_TEST_RUN_KEY_PATH = _TEST_ROOT_KEY_PATH + "\\Run"


def _delete_key_tree(root, path):
    try:
        key = winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return
    try:
        # Subkeys shift down after each deletion, so re-querying index 0
        # each time (rather than enumerating once up front) is required.
        while True:
            try:
                child_name = winreg.EnumKey(key, 0)
            except OSError:
                break
            _delete_key_tree(root, f"{path}\\{child_name}")
    finally:
        winreg.CloseKey(key)
    winreg.DeleteKey(root, path)


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(sr, "_RUN_KEY_PATH", _TEST_RUN_KEY_PATH)
    # set_launch_at_startup() uses OpenKey (not CreateKey), which requires
    # the key to already exist -- unlike the real Run key, our throwaway
    # subkey has to be created up front.
    winreg.CloseKey(winreg.CreateKey(winreg.HKEY_CURRENT_USER, _TEST_RUN_KEY_PATH))
    yield
    _delete_key_tree(winreg.HKEY_CURRENT_USER, _TEST_ROOT_KEY_PATH)


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
