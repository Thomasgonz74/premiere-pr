"""Named bundles of privacy/network settings the user can switch between in
one click for a given usage context (e.g. "voyage", "connexion mobile"),
instead of reopening the Profile tab and changing each field by hand.

SettingsProfile is a deliberately curated subset of Settings -- not the whole
dataclass -- limited to the fields that actually vary by usage context.
Things like theme, default download directory, or history aren't part of a
"context" the way proxy/encryption/rate limits/discovery are.
"""

import json
import os
from dataclasses import asdict, dataclass

from torrent2000.config.paths import get_settings_profiles_path
from torrent2000.config.settings import Settings


@dataclass
class SettingsProfile:
    name: str
    proxy_enabled: bool
    proxy_force: bool
    encryption_mode: str
    notifications_enabled: bool
    download_rate_limit_kbps: int
    upload_rate_limit_kbps: int
    restrict_discovery: bool


class SettingsProfileStore:
    """Persists named SettingsProfile bundles to disk as JSON."""

    def __init__(self) -> None:
        self._profiles: list[SettingsProfile] = []
        self._load()

    def save_from_settings(self, name: str, settings: Settings) -> None:
        """Creates a new profile named `name` from settings' current values,
        replacing any existing profile of the same name."""
        profile = SettingsProfile(
            name=name,
            proxy_enabled=settings.proxy.enabled,
            proxy_force=settings.proxy.force_proxy,
            encryption_mode=settings.encryption_mode,
            notifications_enabled=settings.notifications_enabled,
            download_rate_limit_kbps=settings.download_rate_limit_kbps,
            upload_rate_limit_kbps=settings.upload_rate_limit_kbps,
            restrict_discovery=settings.restrict_discovery,
        )
        self._profiles = [p for p in self._profiles if p.name != name]
        self._profiles.append(profile)
        self._save()

    def list_profiles(self) -> list[SettingsProfile]:
        return list(self._profiles)

    def get_profile(self, name: str) -> SettingsProfile | None:
        return next((p for p in self._profiles if p.name == name), None)

    def delete(self, name: str) -> None:
        self._profiles = [p for p in self._profiles if p.name != name]
        self._save()

    @staticmethod
    def apply_to_settings(profile: SettingsProfile, settings: Settings) -> None:
        """Copies the profile's 7 fields into `settings`, mutating it directly."""
        settings.proxy.enabled = profile.proxy_enabled
        settings.proxy.force_proxy = profile.proxy_force
        settings.encryption_mode = profile.encryption_mode
        settings.notifications_enabled = profile.notifications_enabled
        settings.download_rate_limit_kbps = profile.download_rate_limit_kbps
        settings.upload_rate_limit_kbps = profile.upload_rate_limit_kbps
        settings.restrict_discovery = profile.restrict_discovery

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        path = get_settings_profiles_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        data = [asdict(p) for p in self._profiles]
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_settings_profiles_path()
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
                self._profiles.append(SettingsProfile(**entry))
            except TypeError:
                continue  # malformed/outdated entry -- skip rather than crash on startup
