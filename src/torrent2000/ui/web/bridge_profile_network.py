"""QWebChannel bridge for the Profile tab's "Network" group -- merges three
native sections (NetworkPrivacySection, SecurityCenterSection,
RemoteAccessSection; see ui/tabs/profile_sections.py,
ui/widgets/security_center_section.py, ui/widgets/remote_access_section.py)
into one bridge, since they all live under the same Network heading in the
web UI.

NetworkPrivacySection is save-on-click (getSettings/saveSettings, mirroring
the native Save button's live-apply sequence). RemoteAccessSection's enable
checkbox, port field and "regenerate token" button are live-apply -- see
their dedicated slots below.

remote_access_server is constructed by the caller and passed in rather than
built here, so there is exactly one RemoteAccessServer instance backing the
web UI (the native section constructs its own -- see that module's
docstring for why two instances can coexist there; the web bridge avoids
that by taking one from the caller instead).
"""

import secrets

from PySide6.QtCore import QObject, Slot

from torrent2000.config.settings import Settings
from torrent2000.engine.remote_server import RemoteAccessServer
from torrent2000.engine.session_manager import SessionManager
from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.security_center_section import risk_report_summary


class ProfileNetworkBridge(QObject):
    def __init__(
        self,
        session_manager: SessionManager,
        settings: Settings,
        remote_access_server: RemoteAccessServer,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._remote_access_server = remote_access_server

    # ---------- Network & proxy (save-on-click) ----------

    @Slot(result="QVariantMap")
    def getSettings(self) -> dict:
        s = self._settings
        return {
            "restrictDiscovery": s.restrict_discovery,
            "proxyEnabled": s.proxy.enabled,
            "proxyType": s.proxy.proxy_type,
            "proxyHost": s.proxy.host,
            "proxyPort": s.proxy.port,
            "proxyUsername": s.proxy.username,
            "proxyPassword": s.proxy.password,
            "forceProxy": s.proxy.force_proxy,
            "networkInterface": s.network_interface,
            "encryptionMode": s.encryption_mode,
            "ipBlocklistEnabled": s.ip_blocklist_enabled,
            "ipBlocklistPath": s.ip_blocklist_path,
        }

    @Slot("QVariantMap", result="QVariantMap")
    def saveSettings(self, values: dict) -> dict:
        s = self._settings
        s.restrict_discovery = bool(values.get("restrictDiscovery", s.restrict_discovery))
        s.proxy.enabled = bool(values.get("proxyEnabled", s.proxy.enabled))
        s.proxy.proxy_type = str(values.get("proxyType", s.proxy.proxy_type))
        s.proxy.host = str(values.get("proxyHost", "")).strip()
        s.proxy.port = max(0, min(65535, int(values.get("proxyPort", s.proxy.port))))
        s.proxy.username = str(values.get("proxyUsername", ""))
        s.proxy.password = str(values.get("proxyPassword", ""))
        s.proxy.force_proxy = bool(values.get("forceProxy", s.proxy.force_proxy))
        s.network_interface = str(values.get("networkInterface", "")).strip()
        s.encryption_mode = str(values.get("encryptionMode", s.encryption_mode))
        # Applied once at session start (see SessionManager.__init__) --
        # like network_interface, a change here only takes effect on next
        # launch, not live-applied.
        s.ip_blocklist_enabled = bool(values.get("ipBlocklistEnabled", s.ip_blocklist_enabled))
        s.ip_blocklist_path = str(values.get("ipBlocklistPath", "")).strip()
        saved = s.save()

        # Live-apply, matching the native Save handler's sequence exactly.
        self._session_manager.set_restrict_discovery(s.restrict_discovery)
        self._session_manager.set_proxy(s)
        self._session_manager.set_encryption_mode(s.encryption_mode)
        if not saved:
            return {"ok": False, "error": tr("web.profile_security.save_held_after_import")}
        return {"ok": True}

    # ---------- Security center (read-only) ----------

    @Slot(result="QVariantMap")
    def getSecuritySnapshot(self) -> dict:
        s = self._settings
        scanned, flagged = risk_report_summary(self._session_manager)
        return {
            "proxyEnabled": s.proxy.enabled,
            "discoveryRestricted": s.restrict_discovery,
            "encryptionMode": s.encryption_mode,
            "scannedCount": scanned,
            "flaggedCount": flagged,
        }

    # ---------- Remote access ----------

    @Slot(bool, result="QVariantMap")
    def setRemoteAccessEnabled(self, enabled: bool) -> dict:
        # Live-apply: starts/stops the real listening socket immediately,
        # exactly like the native checkbox (see remote_access_section.py's
        # module docstring for why this one field can't wait for Save).
        s = self._settings
        if enabled:
            if not self._remote_access_server.start():
                return {"ok": False, "error": tr("remote_access.bind_failed_message", port=s.remote_access_port)}
            s.remote_access_enabled = True
            s.save()
            return {"ok": True}
        self._remote_access_server.stop()
        s.remote_access_enabled = False
        s.save()
        return {"ok": True}

    @Slot(result="QVariantMap")
    def getRemoteAccessInfo(self) -> dict:
        s = self._settings
        port = self._remote_access_server.bound_port or s.remote_access_port
        return {
            "enabled": s.remote_access_enabled,
            "port": s.remote_access_port,
            "url": f"http://localhost:{port}",
            "token": s.remote_access_token,
        }

    @Slot(float, result="QVariantMap")
    def setRemoteAccessPort(self, port: float) -> dict:
        # Live-apply like the enable checkbox: a running server is rebound
        # to the new port, or put back on the old one if that fails.
        # The page's min/max don't stop a typed 70000 (or an emptied field, 0).
        # A float, not an int: QWebChannel wrapped a typed 4294967297 to 1
        # before this check saw it.
        if not (float(port).is_integer() and 1 <= port <= 65535):
            return {"ok": False, "error": tr("remote_access.port_out_of_range")}
        port = int(port)
        s = self._settings
        server = self._remote_access_server
        old_port = s.remote_access_port
        s.remote_access_port = port
        if server.is_running:
            server.stop()
            if not server.start():
                s.remote_access_port = old_port
                server.start()
                return {"ok": False, "error": tr("remote_access.bind_failed_message", port=port)}
        s.save()
        return {"ok": True}

    @Slot(result=str)
    def regenerateToken(self) -> str:
        token = secrets.token_urlsafe(24)
        self._settings.remote_access_token = token
        self._settings.save()
        return token
