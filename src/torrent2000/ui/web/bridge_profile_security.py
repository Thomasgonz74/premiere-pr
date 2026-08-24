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

from torrent2000.config.paths import get_config_backups_dir, get_config_path, get_logs_dir
from torrent2000.config.settings import BandwidthSchedule, ProxySettings, RssFeedSubscription, Settings, _from_dict

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
        (backups_dir / f"config-{stamp}.json").write_bytes(config_path.read_bytes())
    except OSError:
        return
    existing = sorted(backups_dir.glob("config-*.json"))
    for stale in existing[:-_MAX_CONFIG_BACKUPS]:
        stale.unlink(missing_ok=True)


def _is_valid_settings_payload(data: object) -> bool:
    """Same shape-check as native ConfigImportExportSection._is_valid_settings_payload."""
    if not isinstance(data, dict):
        return False
    data = dict(data)
    proxy_data = data.pop("proxy", {})
    schedule_data = data.pop("bandwidth_schedule", {})
    rss_feeds_data = data.pop("rss_feeds", [])
    try:
        _from_dict(Settings, data)
        _from_dict(ProxySettings, proxy_data)
        _from_dict(BandwidthSchedule, schedule_data)
        for feed in rss_feeds_data:
            _from_dict(RssFeedSubscription, feed)
    except (TypeError, AttributeError):
        return False
    return True


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
            self._settings.save()
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
        log_path = get_logs_dir() / "torrent2000.log"
        try:
            content = log_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "text": content}

    # -- Config import/export ----------------------------------------------

    @Slot(str, result="QVariantMap")
    def exportConfig(self, path: str) -> dict:
        if not path:
            return {"ok": False}
        # The proxy password must never leave the machine in a plain-text
        # export -- redact it before serializing, matching native
        # ConfigImportExportSection._on_export_settings.
        data = asdict(self._settings)
        if data.get("proxy"):
            data["proxy"]["password"] = ""
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
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"JSON invalide : {exc}"}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if not _is_valid_settings_payload(data):
            return {"ok": False, "error": "Le fichier ne correspond pas à une configuration Torrent 2000 valide."}
        # Snapshot whatever's currently on disk before overwriting it, so a
        # bad or regretted import can be recovered by hand from
        # config_backups/ -- best-effort, never blocks the import itself.
        _backup_current_config()
        # Written straight to the real config file, same as native -- applies
        # fully on next launch, no attempt to hot-reload the running Settings.
        try:
            get_config_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}
