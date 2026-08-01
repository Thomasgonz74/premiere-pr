"""Pure-logic tests for privacy-related settings defaults.

These cover the "zero-config" IP-privacy hardening: a fresh install must
already have restrict_discovery / anonymous-mode-oriented defaults active
without the user ever opening the Settings screen, and a proxy the user
does turn on must default to a fail-closed ("force proxy") kill switch.
"""

import libtorrent as lt

from torrent2000.config.settings import ProxySettings, Settings
from torrent2000.engine import add_params


def test_fresh_settings_restrict_discovery_by_default():
    settings = Settings()
    assert settings.restrict_discovery is True


def test_fresh_proxy_settings_force_proxy_kill_switch_by_default():
    proxy = ProxySettings()
    assert proxy.force_proxy is True
    # ...but the proxy itself is not silently turned on -- the user must
    # supply their own proxy/VPN, per the app's explicit design.
    assert proxy.enabled is False


def test_settings_round_trip_persists_new_privacy_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))

    settings = Settings.load()
    assert settings.restrict_discovery is True
    assert settings.proxy.force_proxy is True

    settings.restrict_discovery = False
    settings.proxy.enabled = True
    settings.proxy.force_proxy = False
    settings.save()

    reloaded = Settings.load()
    assert reloaded.restrict_discovery is False
    assert reloaded.proxy.enabled is True
    assert reloaded.proxy.force_proxy is False


def test_settings_round_trip_defaults_preserved_when_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))

    settings = Settings.load()
    settings.save()

    reloaded = Settings.load()
    assert reloaded.restrict_discovery is True
    assert reloaded.proxy.force_proxy is True


_MAGNET = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=test"

_DISCOVERY_FLAGS = (
    lt.torrent_flags.disable_dht | lt.torrent_flags.disable_pex | lt.torrent_flags.disable_lsd
)


def test_from_magnet_uri_sets_discovery_flags_when_restricted():
    atp = add_params.from_magnet_uri(_MAGNET, "C:/downloads", restrict_discovery=True)
    assert atp.flags & _DISCOVERY_FLAGS == _DISCOVERY_FLAGS


def test_from_magnet_uri_leaves_discovery_flags_unset_by_default():
    atp = add_params.from_magnet_uri(_MAGNET, "C:/downloads")
    assert atp.flags & _DISCOVERY_FLAGS == 0
