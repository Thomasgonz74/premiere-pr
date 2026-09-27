import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from torrent2000.config.paths import get_config_path, get_default_download_dir
from torrent2000.engine import dpapi

SCHEMA_VERSION = 1

# config.json exactly as Settings.save() last wrote it, keyed by path (tests
# switch TORRENT2000_DATA_DIR per case): save() diffs against this instead of
# re-reading the file it just wrote -- reopening a freshly modified file
# triggers a Defender scan, ~14 ms of a ~19 ms save. Anything else that
# writes config.json must call forget_saved_config().
_last_saved_config: dict[str, dict] = {}


def forget_saved_config() -> None:
    _last_saved_config.clear()


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
    # Advanced filters (catalogue idea "filtres RSS avances") -- all optional,
    # applied on top of filter_keyword, never instead of it. Empty/0/False
    # means "no additional constraint", same convention as filter_keyword
    # itself. See engine/rss_feed_service.py::matches_advanced_filters.
    regex_include: str = ""  # item title must match this regex if set
    regex_exclude: str = ""  # item title must NOT match this regex if set
    resolution_min: int = 0  # e.g. 720 -- 0 = no minimum
    resolution_max: int = 0  # e.g. 1080 -- 0 = no maximum
    # When true, only the single item with the highest heuristically-parsed
    # episode/sequence number in a fetch batch is downloaded -- the rest are
    # marked seen (never retried) but never added, avoiding a backlog flood
    # the first time a season-pack-heavy feed is subscribed to.
    latest_episode_only: bool = False


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

    # Off by default -- the pause itself (SessionManager._on_file_error, on a
    # file_error_alert e.g. an external drive dropping out mid-write) always
    # happens regardless of this setting; this only controls whether the
    # torrent is automatically RESUMED once that same drive (matched by
    # volume serial number, not drive letter) reappears. See
    # engine/disk_reconnect_service.py.
    auto_resume_on_disk_reconnect: bool = False

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

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab. When a torrent finishes, writes a
    # "<info_hash>.provenance.json" manifest (info hash, name, completion
    # date, trackers, total size) next to the downloaded files. See
    # engine/session_manager.py's _on_torrent_finished.
    provenance_manifest_enabled: bool = False

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab. See engine/memory_pressure_governor.py: while system
    # memory usage stays at or above memory_governor_threshold_percent,
    # temporarily halves max_active_downloads and pauses RSS feed checks/
    # history writes, restoring both once usage drops back below it.
    memory_governor_enabled: bool = False
    memory_governor_threshold_percent: int = 90  # 0-100

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab. See engine/idle_activity_service.py: once the user
    # has been away from the whole machine (system-wide input idle time, not
    # just idle inside this app) for idle_bandwidth_reduction_minutes,
    # engages BandwidthScheduler's turtle mode; any input activity disables
    # it again immediately.
    idle_bandwidth_reduction_enabled: bool = False
    idle_bandwidth_reduction_minutes: int = 15

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab. See engine/known_disk_service.py: while enabled,
    # periodically checks psutil.disk_partitions() for a newly-inserted disk
    # whose volume LABEL (not drive letter, which can be reassigned) matches
    # one the user has registered (see engine/known_disk_service.py's
    # KnownDiskStore). This only ever emits a confirmation-request signal
    # carrying the disk info and the registered action string -- it NEVER
    # copies/moves/executes anything on its own, no matter how large the
    # associated action implies; the actual confirmation dialog and running
    # the action are a UI/bridge concern.
    known_disk_automation_enabled: bool = False

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab. See engine/network_profile_switcher.py: while
    # enabled, periodically checks the currently-connected Wi-Fi SSID (via
    # `netsh wlan show interfaces`) against SSID->settings-profile
    # associations the user registered (engine/network_profile_switcher.py's
    # NetworkProfileStore) and, on a match, replays the exact live-apply
    # chain bridge_profile_advanced.py's applyProfile uses for a manual
    # profile switch -- not just SettingsProfileStore.apply_to_settings(),
    # which alone only mutates this Settings object in memory.
    network_profile_auto_switch_enabled: bool = False

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab. See engine/peer_reputation.py: while enabled, every
    # SessionManager.get_peer_info() call journals each peer IP's connection
    # stability (average seconds connected before it's observed to drop) and
    # data received from it to a local peer_reputation.json, and the peer
    # list UI shows a per-IP good/neutral/bad badge (bridge_peer_list.py's
    # getReputationScores). Purely local bookkeeping -- never sent anywhere,
    # never affects choking/connection decisions.
    peer_reputation_enabled: bool = False

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab. See engine/lan_peer_cache.py: while enabled, every
    # SessionManager.get_peer_info() call remembers each peer IP that falls
    # inside an RFC1918 private range (10.0.0.0/8, 172.16.0.0/12,
    # 192.168.0.0/16 -- never anything routable/public), keyed by info_hash,
    # to a local lan_peer_cache.json (entries older than 48h are dropped
    # lazily). Re-adding a torrent already seen on this LAN tries to
    # reconnect those remembered peers immediately via handle.connect_peer(),
    # ahead of tracker/DHT/LSD rediscovering them on their own.
    lan_peer_cache_enabled: bool = False

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab and supplies a blocklist file (one CIDR block or IP
    # range per line, "#" comments allowed -- see engine/ip_blocklist.py).
    # Applied once at session start via lt.session.set_ip_filter(); toggling
    # or changing the path takes effect on next launch, same convention as
    # network_interface.
    ip_blocklist_enabled: bool = False
    ip_blocklist_path: str = ""

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab. See engine/scheduled_recheck_service.py: while
    # enabled, periodically force-rechecks finished torrents whose last
    # verification is older than scheduled_recheck_interval_days, to catch
    # silent disk corruption before it's discovered too late.
    scheduled_recheck_enabled: bool = False
    scheduled_recheck_interval_days: int = 30

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab and supplies a URL. See
    # engine/webhook_notification_service.py: POSTs a short plain-text
    # message for the same events already shown as a system tray toast.
    webhook_enabled: bool = False
    webhook_url: str = ""

    # Off by default -- only takes effect once the user explicitly enables it
    # in the Profile tab. See engine/clipboard_watcher_service.py: while
    # enabled, watches the clipboard and offers (never auto-adds) to add a
    # copied magnet: link.
    clipboard_magnet_detection_enabled: bool = False

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
        # Decrypted here, at the JSON-dict boundary, so every Settings field
        # in memory is always plaintext -- see engine/dpapi.py. A pre-existing
        # plaintext value (config saved before this feature existed) passes
        # through unprotect() unchanged and is re-encrypted on the next save().
        if isinstance(proxy_data.get("password"), str):
            proxy_data["password"] = dpapi.unprotect(proxy_data["password"])
        if isinstance(data.get("remote_access_token"), str):
            data["remote_access_token"] = dpapi.unprotect(data["remote_access_token"])
        settings = _from_dict(Settings, data)
        settings.proxy = _from_dict(ProxySettings, proxy_data)
        settings.bandwidth_schedule = _from_dict(BandwidthSchedule, schedule_data)
        settings.rss_feeds = [_from_dict(RssFeedSubscription, feed) for feed in rss_feeds_data]
        if not settings.default_download_dir:
            settings.default_download_dir = str(get_default_download_dir())
        return settings

    def save(self) -> None:
        path = get_config_path()
        # The state being overwritten, so the diff-based history log
        # (settings_history.py) can journal only what changed: what this
        # process last wrote if known (see _last_saved_config), else whatever's
        # on disk. None on first-ever save (no prior state to diff against)
        # or if the existing file is unreadable -- either way, nothing gets
        # journaled.
        old_data = _last_saved_config.get(str(path))
        if old_data is None and path.exists():
            try:
                old_data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                old_data = None
        new_data = asdict(self)
        # Encrypted only in the dict about to be written to disk -- `self`
        # (and therefore old_data's diff below, which excludes both fields
        # entirely anyway -- see settings_history._EXCLUDED_FIELDS) keeps
        # plaintext in memory throughout.
        new_data["proxy"]["password"] = dpapi.protect(new_data["proxy"]["password"])
        new_data["remote_access_token"] = dpapi.protect(new_data["remote_access_token"])
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(new_data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)
        _last_saved_config[str(path)] = new_data
        if old_data is not None:
            # Local import: settings_history imports Settings/_from_dict back
            # for restore_settings_snapshot, so this stays a lazy call-time
            # import to avoid a circular import at module load.
            from torrent2000.config.settings_history import record_settings_change

            record_settings_change(old_data, new_data)
