"""Registers/unregisters Torrent 2000 in the current user's Windows startup
programs (HKCU Run key) -- the standard, no-admin-rights way apps offer a
"launch at startup" toggle, used instead of a Startup-folder shortcut since
it needs no separate .lnk file to create/find/delete.
"""

import sys
from pathlib import Path

import winreg

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "Torrent2000"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Running from source (dev machine): sys.executable is python.exe, so the
    # entry script must be included too or Windows would just launch a bare
    # interpreter with nothing to run.
    return f'"{sys.executable}" "{Path(sys.argv[0]).resolve()}"'


def set_launch_at_startup(enabled: bool) -> None:
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
    try:
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def is_launch_at_startup_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return False
    try:
        winreg.QueryValueEx(key, _VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)
