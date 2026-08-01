"""Translate user-facing proxy settings into libtorrent's settings-dict fragment.

This wraps configuration of an existing proxy/VPN endpoint the user already
has (SOCKS5/HTTP), matching libtorrent's own proxy_settings model. It does
not implement any anonymity network of its own.
"""

import libtorrent as lt

from torrent2000.config.settings import ProxySettings

_TYPE_MAP = {
    "none": lt.proxy_type_t.none,
    "socks5": lt.proxy_type_t.socks5,
    "socks5_pw": lt.proxy_type_t.socks5_pw,
    "http": lt.proxy_type_t.http,
    "http_pw": lt.proxy_type_t.http_pw,
}


def build_settings_fragment(proxy: ProxySettings) -> dict:
    if not proxy.enabled or proxy.proxy_type == "none":
        return {
            "proxy_type": int(lt.proxy_type_t.none),
            "proxy_hostname": "",
            "proxy_port": 0,
            "proxy_username": "",
            "proxy_password": "",
            "force_proxy": False,
        }

    proxy_type = _TYPE_MAP.get(proxy.proxy_type, lt.proxy_type_t.none)
    return {
        "proxy_type": int(proxy_type),
        "proxy_hostname": proxy.host,
        "proxy_port": proxy.port,
        "proxy_username": proxy.username,
        "proxy_password": proxy.password,
        "proxy_peer_connections": proxy.proxy_peer_connections,
        "proxy_tracker_connections": proxy.proxy_tracker_connections,
        "force_proxy": proxy.force_proxy,
    }


def build_interface_fragment(interface_name: str) -> dict:
    if not interface_name:
        return {}
    return {
        "listen_interfaces": f"{interface_name}:6881",
        "outgoing_interfaces": interface_name,
    }
