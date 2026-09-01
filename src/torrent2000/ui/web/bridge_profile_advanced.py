"""QWebChannel bridge backing the Profile tab's "Advanced/Rules" group --
RoutingRulesSection + SettingsProfilesSection. Mirrors both widgets exactly:
every action (add/edit/delete/reorder a routing rule; apply/save-as/delete a
settings profile) hits its store directly and, for "apply profile", the same
live session_manager calls as SettingsProfilesSection's Apply button -- no
batched save, same live-apply-only convention as the native sections.

Also backs the (new, no native equivalent) network-profile auto-switch
group: SSID->settings-profile associations live here rather than in
bridge_profile_automation.py because they reference settings profiles by
name, and this is where those profiles already live. The actual live-apply
logic runs in engine/network_profile_switcher.py's NetworkProfileSwitcherService
on its own timer -- this bridge only manages the on/off flag and the
association list, same "store CRUD, no batched save" convention as this
file's other two sections.
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.config.settings import Settings
from torrent2000.engine.network_profile_switcher import NetworkProfileAssociation, NetworkProfileStore
from torrent2000.engine.routing_rules import RoutingRule, RoutingRuleStore
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.settings_profiles import SettingsProfile, SettingsProfileStore


def _rule_to_dict(rule: RoutingRule) -> dict:
    return {
        "name": rule.name,
        "pattern": rule.pattern,
        "matchField": rule.match_field,
        "destination": rule.destination,
    }


def _profile_to_dict(profile: SettingsProfile) -> dict:
    return {
        "name": profile.name,
        "proxyEnabled": profile.proxy_enabled,
        "proxyForce": profile.proxy_force,
        "encryptionMode": profile.encryption_mode,
        "notificationsEnabled": profile.notifications_enabled,
        "downloadRateLimitKbps": profile.download_rate_limit_kbps,
        "uploadRateLimitKbps": profile.upload_rate_limit_kbps,
        "restrictDiscovery": profile.restrict_discovery,
    }


def _network_profile_to_dict(association: NetworkProfileAssociation) -> dict:
    return {"ssid": association.ssid, "profileName": association.profile_name}


class ProfileAdvancedBridge(QObject):
    def __init__(
        self,
        session_manager: SessionManager,
        settings: Settings,
        routing_rule_store: RoutingRuleStore,
        settings_profile_store: SettingsProfileStore,
        network_profile_store: NetworkProfileStore,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._routing_rule_store = routing_rule_store
        self._settings_profile_store = settings_profile_store
        self._network_profile_store = network_profile_store

    # ------------------------------------------------------------ routing rules

    @Slot(result="QVariantList")
    def listRoutingRules(self) -> list:
        return [_rule_to_dict(rule) for rule in self._routing_rule_store.list_rules()]

    @Slot(str, str, str, str)
    def saveRoutingRule(self, name: str, pattern: str, match_field: str, destination: str) -> None:
        # save_rule() both adds a new rule and edits an existing one in
        # place (same name = same priority slot) -- see its docstring.
        rule = RoutingRule(name=name, pattern=pattern, match_field=match_field, destination=destination)
        self._routing_rule_store.save_rule(rule)

    @Slot(str)
    def deleteRoutingRule(self, name: str) -> None:
        self._routing_rule_store.delete(name)

    @Slot("QVariantList")
    def reorderRoutingRules(self, names) -> None:
        self._routing_rule_store.reorder(list(names))

    # --------------------------------------------------------- settings profiles

    @Slot(result="QVariantList")
    def listSettingsProfiles(self) -> list:
        return [_profile_to_dict(p) for p in self._settings_profile_store.list_profiles()]

    @Slot(str, result="QVariantMap")
    def saveCurrentAsProfile(self, name: str) -> dict:
        self._settings_profile_store.save_from_settings(name, self._settings)
        return {"ok": True}

    @Slot(str, result="QVariantMap")
    def applyProfile(self, name: str) -> dict:
        profile = self._settings_profile_store.get_profile(name)
        if profile is None:
            return {"ok": False, "error": "Profil introuvable."}
        # Same live-apply calls, in the same order, as SettingsProfilesSection's
        # Apply button (see settings_profiles_section.py's _on_apply_clicked).
        self._settings_profile_store.apply_to_settings(profile, self._settings)
        self._settings.save()
        self._session_manager.set_rate_limits(
            self._settings.download_rate_limit_kbps, self._settings.upload_rate_limit_kbps
        )
        self._session_manager.set_restrict_discovery(self._settings.restrict_discovery)
        self._session_manager.set_proxy(self._settings)
        self._session_manager.set_encryption_mode(self._settings.encryption_mode)
        return {"ok": True}

    @Slot(str)
    def deleteSettingsProfile(self, name: str) -> None:
        self._settings_profile_store.delete(name)

    # ------------------------------------------- network profile auto-switch

    @Slot(result="QVariantMap")
    def getNetworkProfileSwitchSettings(self) -> dict:
        return {"enabled": self._settings.network_profile_auto_switch_enabled}

    @Slot(bool, result="QVariantMap")
    def setNetworkProfileSwitchEnabled(self, enabled: bool) -> dict:
        self._settings.network_profile_auto_switch_enabled = bool(enabled)
        self._settings.save()
        return {"ok": True}

    @Slot(result="QVariantList")
    def listNetworkProfileAssociations(self) -> list:
        return [_network_profile_to_dict(a) for a in self._network_profile_store.list_associations()]

    @Slot(str, str, result="QVariantMap")
    def saveNetworkProfileAssociation(self, ssid: str, profile_name: str) -> dict:
        ssid = (ssid or "").strip()
        profile_name = (profile_name or "").strip()
        if not ssid:
            return {"ok": False, "error": "Le nom du réseau (SSID) est requis."}
        if not profile_name:
            return {"ok": False, "error": "Un profil de réglages doit être sélectionné."}
        self._network_profile_store.save_association(NetworkProfileAssociation(ssid=ssid, profile_name=profile_name))
        return {"ok": True}

    @Slot(str)
    def deleteNetworkProfileAssociation(self, ssid: str) -> None:
        self._network_profile_store.delete(ssid)
