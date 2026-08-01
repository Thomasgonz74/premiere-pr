import json
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
class Settings:
    schema_version: int = SCHEMA_VERSION
    default_download_dir: str = ""
    download_rate_limit_kbps: int = 0  # 0 = unlimited
    upload_rate_limit_kbps: int = 0
    danger_auto_exclude_threshold: int = 60  # 0-100, files scoring >= this get auto-excluded
    theme: str = "luna_xp"
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
        settings = Settings(**{k: v for k, v in data.items() if k in Settings.__dataclass_fields__})
        settings.proxy = ProxySettings(**{k: v for k, v in proxy_data.items() if k in ProxySettings.__dataclass_fields__})
        if not settings.default_download_dir:
            settings.default_download_dir = str(get_default_download_dir())
        return settings

    def save(self) -> None:
        path = get_config_path()
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
