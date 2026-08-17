import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from torrent2000.config.paths import get_config_path, get_default_download_dir

SCHEMA_VERSION = 1


@dataclass
class ProxySettings:
    enabled: bool = False
    proxy_type: str = "none"  # none | socks5 | socks5_pw | http | http_pw
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    proxy_peer_connections: bool = True
    proxy_tracker_connections: bool = True
    # Kill switch: once a proxy is enabled, refuse any connection that would
    # bypass it rather than silently falling back to a direct (unmasked)
    # connection. Defaults to True so turning the proxy on is "safe by
    # default", matching qBittorrent-style "force proxy" behavior. This has
    # no effect while `enabled` is False (see proxy.build_settings_fragment).
    force_proxy: bool = True


@dataclass
class BandwidthSchedule:
    """A single reduced-speed window applied daily, e.g. "throttled during
    the day, unlimited at night". Outside the window, Settings'
    download_rate_limit_kbps/upload_rate_limit_kbps apply as normal."""

    enabled: bool = False
    start_hour: int = 8  # 0-23, local time
    end_hour: int = 22  # 0-23; if end_hour < start_hour the window wraps past midnight
    limited_download_kbps: int = 0  # 0 = unlimited even during the window
    limited_upload_kbps: int = 0


@dataclass
class RssFeedSubscription:
    url: str = ""
    filter_keyword: str = ""  # empty = match every item in the feed
    enabled: bool = True


def _from_dict(cls, raw: dict):
    """Builds a dataclass instance from a raw dict, silently dropping any
    key that isn't one of the dataclass's own fields -- so a settings.json
    left over from an older/newer schema version loads without a
    TypeError on unexpected keys."""
    return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


@dataclass
class Settings:
    schema_version: int = SCHEMA_VERSION
    default_download_dir: str = ""
    download_rate_limit_kbps: int = 0  # 0 = unlimited
    upload_rate_limit_kbps: int = 0
    danger_auto_exclude_threshold: int = 60  # 0-100, files scoring >= this get auto-excluded
    theme: str = "luna_xp"
    appearance_mode: str = "light"  # "light" | "dark" | "dark_hc"
    language: str = "fr"  # see i18n/translator.py LANGUAGE_LABELS for the full list
    network_interface: str = ""  # empty = default / all interfaces
    proxy: ProxySettings = field(default_factory=ProxySettings)
    max_active_downloads: int = 8
    # Zero-config privacy hardening (see engine/session_manager.py and
    # engine/add_params.py): disables DHT, PEX and LSD, which broadcast a
    # client's IP to a much wider audience (a global public DHT network of
    # many thousands of nodes) than just the peers it actively exchanges
    # data with. This does NOT hide the IP from swarm peers themselves --
    # that is only possible by relaying traffic through a proxy/VPN the
    # user configures below -- it only limits how far the IP is broadcast.
    restrict_discovery: bool = True
    bandwidth_schedule: BandwidthSchedule = field(default_factory=BandwidthSchedule)

    # Default share policy, auto-applied the moment ANY torrent (not just ones
    # manually tracked via the Partage tab) transitions to seeding -- off by
    # default so existing behavior (unlimited seeding unless manually tracked)
    # is unchanged until the user opts in.
    default_share_policy_enabled: bool = False
    default_share_ratio_limit: float = 0.0  # 0 = no ratio cap
    default_share_time_limit_hours: int = 0  # 0 = no time cap
    default_share_data_limit_mb: int = 0  # 0 = no data cap

    notifications_enabled: bool = True
    minimize_to_tray: bool = True  # closing the window hides it to the system tray instead of quitting

    rss_feeds: list[RssFeedSubscription] = field(default_factory=list)

    watch_folder_enabled: bool = False
    watch_folder_path: str = ""

    disk_space_warning_enabled: bool = True
    disk_space_warning_threshold_mb: int = 1024  # warn when free space at a destination drops below this

    # libtorrent enc_policy: 0=forced, 1=enabled, 2=disabled (default "enabled"
    # already prefers encryption but allows a plaintext fallback so it can
    # still reach peers that don't support it -- "forced" refuses plaintext
    # outright, useful against ISP throttling of recognizable BitTorrent
    # traffic; distinct from the IP-hiding proxy settings above).
    encryption_mode: str = "enabled"  # "forced" | "enabled" | "disabled"

    # Off by default -- only takes effect once the user explicitly enables it in
    # the Profile tab's Security section. Runs a Windows Defender custom scan on
    # a torrent's files after it finishes downloading; never writes an exclusion,
    # only ever scans.
    scan_completed_files_with_defender: bool = False

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab.
    auto_shutdown_enabled: bool = False
    auto_shutdown_action: str = "shutdown"  # "shutdown" | "hibernate"
    auto_shutdown_delay_seconds: int = 60  # cancellable countdown before it actually fires

    # Off by default -- only takes effect once the user explicitly enables it in
    # the Profile tab. Pauses active downloads on battery power, resumes them
    # once external power returns; reversible, not destructive (matches
    # auto_shutdown's own opt-in convention).
    pause_on_battery_enabled: bool = False

    # Off by default -- opens a small local HTTP server (see
    # engine/remote_server.py) so torrent progress can be checked, and a
    # share paused/resumed, from a phone on the same local network. It has
    # to listen on every network interface to be reachable from another
    # device, so remote_access_token is the ONLY thing standing between
    # anyone on that network and the API -- never enabled without an
    # explicit opt-in, same convention as scan_completed_files_with_defender/
    # auto_shutdown_enabled/pause_on_battery_enabled above.
    remote_access_enabled: bool = False
    remote_access_port: int = 8642  # deliberately not a common dev-server port (3000/8080/5000/...)
    # Generated via secrets.token_urlsafe(24) the first time the server is
    # actually started (see RemoteAccessServer.start) -- never chosen by the
    # user, never predictable. Regenerable on demand from the Profile tab.
    remote_access_token: str = ""

    audio_volume: int = 70  # 0-100, currently drives only the CCCP theme's anthem playback

    launch_at_startup: bool = False  # mirrors the actual HKCU Run key state, see engine/startup_registration.py

    check_for_updates: bool = True
    # Set when the user dismisses an update notification, so the same
    # already-seen version doesn't nag again every launch -- a genuinely
    # newer release still triggers a fresh notification.
    dismissed_update_version: str = ""

    # Set once the one-time welcome dialog (see ui/onboarding_dialog.py) has
    # been acknowledged, so it only ever shows on the very first launch.
    first_launch_seen: bool = False

    @staticmethod
    def load() -> "Settings":
        path = get_config_path()
        if not path.exists():
            settings = Settings()
            settings.default_download_dir = str(get_default_download_dir())
            settings.save()
            return settings
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            settings = Settings()
            settings.default_download_dir = str(get_default_download_dir())
            return settings
        proxy_data = data.pop("proxy", {})
        schedule_data = data.pop("bandwidth_schedule", {})
        rss_feeds_data = data.pop("rss_feeds", [])
        settings = _from_dict(Settings, data)
        settings.proxy = _from_dict(ProxySettings, proxy_data)
        settings.bandwidth_schedule = _from_dict(BandwidthSchedule, schedule_data)
        settings.rss_feeds = [_from_dict(RssFeedSubscription, feed) for feed in rss_feeds_data]
        if not settings.default_download_dir:
            settings.default_download_dir = str(get_default_download_dir())
        return settings

    def save(self) -> None:
        path = get_config_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)
