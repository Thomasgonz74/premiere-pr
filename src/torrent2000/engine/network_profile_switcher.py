"""Optional automatic settings-profile switching based on the currently
connected Wi-Fi SSID (catalogue "idees non implementees", cluster
Automatisation contextuelle) -- e.g. auto-apply a "Domicile" profile at home
and a "Public" profile (proxy forced, DHT/PEX/LSD restricted) on any other
network.

OFF BY DEFAULT (see Settings.network_profile_auto_switch_enabled) -- same
opt-in convention as BatteryPauseService/DiskReconnectService.

CRITICAL: SettingsProfileStore.apply_to_settings() only mutates the Settings
object in memory -- it does NOT touch the running libtorrent session. Once a
match is found, _apply_profile() below replays the *exact* live-apply chain
bridge_profile_advanced.py's applyProfile uses for a manual profile switch
(apply_to_settings -> settings.save() -> set_rate_limits ->
set_restrict_discovery -> set_proxy -> set_encryption_mode). Skipping any one
of those means the switch looks like it "took" (Settings + config.json
updated) while the active session keeps running under the old policy.

SSID detection is Windows-only (`netsh wlan show interfaces`), matching this
project's Windows-only scope (see volume_serial.py for the same ctypes-era
"Windows only, no cross-platform guard" convention). Not connected to Wi-Fi,
no Wi-Fi adapter present, or netsh missing/erroring are all treated the same
as "no SSID right now" -- silently skip, never raise.

Persistence follows the same tmp-file + os.replace() pattern as
engine/known_disk_service.py.
"""

import json
import logging
import os
import subprocess
from dataclasses import asdict, dataclass

from PySide6.QtCore import QObject

from torrent2000.config.paths import get_network_profiles_path
from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.settings_profiles import SettingsProfile, SettingsProfileStore
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 20_000


@dataclass
class NetworkProfileAssociation:
    ssid: str  # Wi-Fi network name, matched case-sensitively as-is
    profile_name: str  # name of a SettingsProfile registered in SettingsProfileStore


class NetworkProfileStore:
    """Persists SSID->settings-profile-name associations to disk as JSON."""

    def __init__(self) -> None:
        self._associations: list[NetworkProfileAssociation] = []
        self._load()

    def list_associations(self) -> list[NetworkProfileAssociation]:
        return list(self._associations)

    def save_association(self, association: NetworkProfileAssociation) -> None:
        """Adds `association`, or replaces the existing one for the same SSID."""
        for i, existing in enumerate(self._associations):
            if existing.ssid == association.ssid:
                self._associations[i] = association
                self._save()
                return
        self._associations.append(association)
        self._save()

    def delete(self, ssid: str) -> None:
        self._associations = [a for a in self._associations if a.ssid != ssid]
        self._save()

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        path = get_network_profiles_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        data = [asdict(a) for a in self._associations]
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_network_profiles_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, list):
            return  # malformed top-level shape -- start empty rather than crash on startup
        for entry in data:
            try:
                self._associations.append(NetworkProfileAssociation(**entry))
            except TypeError:
                continue  # malformed/outdated entry -- skip rather than crash on startup


def get_current_ssid() -> str | None:
    """Returns the SSID of the currently-connected Wi-Fi network, or None if
    not connected to Wi-Fi, there's no Wi-Fi adapter, or `netsh` itself is
    unavailable/errors/times out. There is no documented Win32/psutil API
    for "current SSID" -- `netsh wlan show interfaces` text output is the
    standard way to get it on Windows, "SSID"/"BSSID" labels are not
    localized even on non-English Windows.

    encoding="oem" decodes using the console/OEM codepage netsh actually
    writes in (e.g. cp850), not the ANSI codepage `text=True` alone would
    assume -- the classic Windows subprocess-output mismatch. errors=
    "replace" means a still-wrong guess degrades to garbled characters
    rather than crashing a background timer tick.
    """
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("SSID") and ":" in line:  # excludes "BSSID" lines (start with "B")
            return line.split(":", 1)[1].strip() or None
    return None


class NetworkProfileSwitcherService(QObject):
    def __init__(
        self,
        session_manager: SessionManager,
        settings: Settings,
        store: NetworkProfileStore,
        settings_profile_store: SettingsProfileStore,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._store = store
        self._settings_profile_store = settings_profile_store
        # Last SSID actually seen -- so an unchanged connection doesn't
        # replay the live-apply chain (or even look up the association list)
        # on every single tick.
        # ponytail: this cache is keyed on the SSID string alone, so adding
        # an association *while already connected* to that SSID won't take
        # effect until the SSID changes (disconnect/reconnect) or the app
        # restarts. Upgrade: reset _last_ssid whenever the store changes.
        self._last_ssid: str | None = None

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.check_now)

    def check_now(self) -> None:
        if not self._settings.network_profile_auto_switch_enabled:
            return

        ssid = get_current_ssid()
        if ssid is None or ssid == self._last_ssid:
            return
        self._last_ssid = ssid

        association = next((a for a in self._store.list_associations() if a.ssid == ssid), None)
        if association is None:
            return
        profile = next(
            (p for p in self._settings_profile_store.list_profiles() if p.name == association.profile_name),
            None,
        )
        if profile is None:
            return  # profile was renamed/deleted after the association was made -- nothing to apply

        self._apply_profile(profile)

    def _apply_profile(self, profile: SettingsProfile) -> None:
        # EXACT same live-apply chain, same order, as
        # bridge_profile_advanced.py's applyProfile (manual profile switch).
        self._settings_profile_store.apply_to_settings(profile, self._settings)
        self._settings.save()
        self._session_manager.set_rate_limits(
            self._settings.download_rate_limit_kbps, self._settings.upload_rate_limit_kbps
        )
        self._session_manager.set_restrict_discovery(self._settings.restrict_discovery)
        self._session_manager.set_proxy(self._settings)
        self._session_manager.set_encryption_mode(self._settings.encryption_mode)
        logger.info("Network profile auto-switch: applied profile %r for SSID %r", profile.name, self._last_ssid)
