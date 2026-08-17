"""Coverage for translating ProxySettings into libtorrent settings-dict
fragments: one case per proxy_type, the disabled/neutral fallback, and the
network-interface fragment."""

import libtorrent as lt
import pytest

from torrent2000.config.settings import ProxySettings
from torrent2000.engine.proxy import build_interface_fragment, build_settings_fragment

_DISABLED_FRAGMENT = {
    "proxy_type": int(lt.proxy_type_t.none),
    "proxy_hostname": "",
    "proxy_port": 0,
    "proxy_username": "",
    "proxy_password": "",
    "force_proxy": False,
}


def _enabled_proxy(proxy_type: str) -> ProxySettings:
    return ProxySettings(
        enabled=True,
        proxy_type=proxy_type,
        host="proxy.example.com",
        port=1080,
        username="alice",
        password="s3cret",
        proxy_peer_connections=False,
        proxy_tracker_connections=True,
        force_proxy=True,
    )


@pytest.mark.parametrize(
    ("proxy_type", "expected_lt_type"),
    [
        ("socks5", lt.proxy_type_t.socks5),
        ("socks5_pw", lt.proxy_type_t.socks5_pw),
        ("http", lt.proxy_type_t.http),
        ("http_pw", lt.proxy_type_t.http_pw),
    ],
)
def test_build_settings_fragment_for_each_enabled_proxy_type(proxy_type, expected_lt_type):
    fragment = build_settings_fragment(_enabled_proxy(proxy_type))

    assert fragment == {
        "proxy_type": int(expected_lt_type),
        "proxy_hostname": "proxy.example.com",
        "proxy_port": 1080,
        "proxy_username": "alice",
        "proxy_password": "s3cret",
        "proxy_peer_connections": False,
        "proxy_tracker_connections": True,
        "force_proxy": True,
    }


def test_build_settings_fragment_for_type_none_returns_disabled_fragment_even_when_enabled():
    proxy = _enabled_proxy("none")

    fragment = build_settings_fragment(proxy)

    assert fragment == _DISABLED_FRAGMENT


def test_build_settings_fragment_returns_disabled_fragment_when_not_enabled():
    """enabled=False must return the neutral fragment regardless of what the
    other fields (host/port/type/credentials) happen to contain."""
    proxy = _enabled_proxy("socks5_pw")
    proxy.enabled = False

    fragment = build_settings_fragment(proxy)

    assert fragment == _DISABLED_FRAGMENT


def test_build_interface_fragment_empty_interface_returns_empty_dict():
    assert build_interface_fragment("") == {}


def test_build_interface_fragment_non_empty_interface_targets_that_nic():
    fragment = build_interface_fragment("Ethernet")

    assert fragment == {
        "listen_interfaces": "Ethernet:6881",
        "outgoing_interfaces": "Ethernet",
    }
