"""QWebChannel bridge backing the Profile tab's Security/Diagnostics/Config
sections -- mirrors SecuritySection, DiagnosticsSection, and
ConfigImportExportSection from profile_sections.py exactly (proxy password
redaction on export, _is_valid_settings_payload's validation on import,
write-to-disk-only-applies-on-next-launch for import).
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_config_backups_dir, get_config_path, get_logs_dir, retry_if_dir_vanished
from torrent2000.config.redaction import redact_settings_dict
from torrent2000.config.settings import (
    BandwidthSchedule,
    ProxySettings,
    RssFeedSubscription,
    Settings,
    _from_dict,
    hold_config_until_restart,
)
from torrent2000.i18n.translator import tr

_MAX_CONFIG_BACKUPS = 5


def _backup_current_config() -> None:
    """Best-effort timestamped snapshot of the config file as it stands right
    before an import overwrites it, so a bad/regretted import is recoverable.
    Silently skipped if there's nothing to back up yet (first-ever launch) --
    this is a safety net for imports, not a general backup feature."""
    config_path = get_config_path()
    if not config_path.exists():
        return
    backups_dir = get_config_backups_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        # Redacted like exportConfig() -- a backup is a copy that can end up
        # shared for support/troubleshooting just as easily as an export.
        data = redact_settings_dict(json.loads(config_path.read_text(encoding="utf-8")))
        text = json.dumps(data, indent=2, ensure_ascii=False)
        # config_backups/ holds no open handle, so the user can delete it mid-run.
        retry_if_dir_vanished(
            lambda: (get_config_backups_dir() / f"config-{stamp}.json").write_text(text, encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return
    existing = sorted(backups_dir.glob("config-*.json"))
    for stale in existing[:-_MAX_CONFIG_BACKUPS]:
        stale.unlink(missing_ok=True)


def _keeps_every_value(cls, raw: object) -> bool:
    """Every field of cls in raw loads as it is: none falls back to its
    default for a value of the wrong type (see settings._typed)."""
    if not isinstance(raw, dict):
        return False
    built = _from_dict(cls, raw)
    return all(getattr(built, key) == value for key, value in raw.items() if key in cls.__dataclass_fields__)


def _is_valid_settings_payload(data: object) -> bool:
    """Same shape-check as native ConfigImportExportSection._is_valid_settings_payload,
    plus every value's type: a "fast" rate limit was imported, and the app
    could never start again."""
    if not isinstance(data, dict):
        return False
    # _from_dict drops unknown keys, so any JSON object passed the checks
    # below: one sharing no field with Settings is some other app's file.
    if not data.keys() & Settings.__dataclass_fields__.keys():
        return False
    data = dict(data)
    feeds = data.pop("rss_feeds", [])
    return (
        _keeps_every_value(ProxySettings, data.pop("proxy", {}))
        and _keeps_every_value(BandwidthSchedule, data.pop("bandwidth_schedule", {}))
        and isinstance(feeds, list)
        and all(_keeps_every_value(RssFeedSubscription, feed) for feed in feeds)
        and _keeps_every_value(Settings, data)
    )


class ProfileSecurityBridge(QObject):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings

    # -- Security --------------------------------------------------------

    @Slot(result="QVariantMap")
    def getSettings(self) -> dict:
        return {"scanCompletedFilesWithDefender": self._settings.scan_completed_files_with_defender}

    @Slot("QVariantMap", result="QVariantMap")
    def saveSettings(self, values) -> dict:
        try:
            self._settings.scan_completed_files_with_defender = bool(values.get("scanCompletedFilesWithDefender"))
            if not self._settings.save():
                return {"ok": False, "error": tr("web.profile_security.save_held_after_import")}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    @Slot()
    def openDefender(self) -> None:
        QDesktopServices.openUrl(QUrl("windowsdefender://threatsettings"))

    # -- Diagnostics -------------------------------------------------------

    @Slot()
    def openLogsFolder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_logs_dir())))

    @Slot(result="QVariantMap")
    def copyLogToClipboard(self) -> dict:
        # Copied Python-side: shipping up to 5 MB of log through QWebChannel
        # just for navigator.clipboard cost four copies per click (and that
        # API rejects when the page doesn't have focus).
        log_path = get_logs_dir() / "torrent2000.log"
        try:
            content = log_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        clipboard = QApplication.clipboard()
        clipboard.setText(content)
        # setText never raises: on Windows a failed OleSetClipboard is only
        # a Qt warning. Reading back is cheap while Qt owns the clipboard.
        if clipboard.text() != content:
            return {"ok": False, "clipboardError": True}
        return {"ok": True}

    # -- Config import/export ----------------------------------------------

    @Slot(str, result="QVariantMap")
    def exportConfig(self, path: str) -> dict:
        if not path:
            return {"ok": False}
        # Secrets (proxy password, remote-access token, webhook URL, RSS
        # passkeys) must never leave the machine in a plain-text export.
        data = redact_settings_dict(asdict(self._settings))
        try:
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    @Slot(str, result="QVariantMap")
    def importConfig(self, path: str) -> dict:
        if not path:
            return {"ok": False}
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"ok": False, "error": tr("profile_tab.import_failed_message_invalid")}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if not _is_valid_settings_payload(data):
            return {"ok": False, "error": tr("profile_tab.import_failed_message_schema")}
        # Snapshot whatever's currently on disk before overwriting it, so a
        # bad or regretted import can be recovered by hand from
        # config_backups/ -- best-effort, never blocks the import itself.
        _backup_current_config()
        # Written straight to the real config file, same as native -- applies
        # fully on next launch, no attempt to hot-reload the running Settings,
        # which therefore must not save its own state over it until then.
        try:
            get_config_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        hold_config_until_restart()
        return {"ok": True}
