"""Minimal coverage for lan_peer_cache.py (opt-in, off by default -- see
Settings.lan_peer_cache_enabled): the RFC1918 filter, persistence (mirrors
test_peer_reputation.py's isolated_data_dir pattern), the lazy 48h purge, and
reconnect_cached_peers() at torrent-add time.
"""

import time

import pytest

from torrent2000.engine.lan_peer_cache import (
    MAX_AGE_SECONDS,
    LanPeerCacheStore,
    is_rfc1918,
    reconnect_cached_peers,
)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class FakePeer:
    def __init__(self, ip, port):
        self.ip = (ip, port)


class FakeHandle:
    def __init__(self):
        self.connected: list[tuple[str, int]] = []

    def connect_peer(self, endpoint):
        self.connected.append(endpoint)


# --------------------------------------------------------------------- is_rfc1918


@pytest.mark.parametrize(
    "ip",
    ["10.0.0.1", "10.255.255.255", "172.16.0.1", "172.31.255.255", "192.168.0.1", "192.168.255.255"],
)
def test_is_rfc1918_accepts_the_three_private_blocks(ip):
    assert is_rfc1918(ip) is True


@pytest.mark.parametrize(
    "ip",
    [
        "172.15.255.255",  # just below 172.16.0.0/12
        "172.32.0.1",  # just above it
        "8.8.8.8",  # public
        "127.0.0.1",  # loopback -- not RFC1918
        "169.254.1.1",  # link-local -- not RFC1918
        "fe80::1",  # IPv6 out of scope
        "not-an-ip",  # malformed -- must not raise
    ],
)
def test_is_rfc1918_rejects_everything_else(ip):
    assert is_rfc1918(ip) is False


# ------------------------------------------------------------------ LanPeerCacheStore


def test_store_starts_empty_when_no_file_exists():
    assert LanPeerCacheStore().get_peers("hashA") == []


def test_record_peers_keeps_only_private_ips_and_persists():
    store = LanPeerCacheStore()
    store.record_peers("hashA", [FakePeer("8.8.8.8", 6881), FakePeer("192.168.1.50", 51413)])

    assert store.get_peers("hashA") == [("192.168.1.50", 51413)]

    reloaded = LanPeerCacheStore()
    assert reloaded.get_peers("hashA") == [("192.168.1.50", 51413)]


def test_record_peers_keeps_hashes_separate():
    store = LanPeerCacheStore()
    store.record_peers("hashA", [FakePeer("10.0.0.5", 6881)])
    store.record_peers("hashB", [FakePeer("10.0.0.6", 6881)])

    assert store.get_peers("hashA") == [("10.0.0.5", 6881)]
    assert store.get_peers("hashB") == [("10.0.0.6", 6881)]


def test_expired_entries_are_purged_lazily_on_read():
    store = LanPeerCacheStore()
    store.record_peers("hashA", [FakePeer("10.1.2.3", 6881)])
    # backdate past the 48h cutoff directly rather than sleeping in a test
    store._entries["hashA"]["10.1.2.3"].last_seen = time.time() - MAX_AGE_SECONDS - 1

    assert store.get_peers("hashA") == []
    assert "hashA" not in store._entries  # emptied per-hash dict is dropped entirely


def test_fresh_entry_survives_purge():
    store = LanPeerCacheStore()
    store.record_peers("hashA", [FakePeer("10.1.2.3", 6881)])
    store._entries["hashA"]["10.1.2.3"].last_seen = time.time() - (MAX_AGE_SECONDS - 60)

    assert store.get_peers("hashA") == [("10.1.2.3", 6881)]


# --------------------------------------------------------------- reconnect_cached_peers


def test_reconnect_cached_peers_calls_connect_peer_for_each_cached_entry():
    store = LanPeerCacheStore()
    store.record_peers("hashC", [FakePeer("192.168.0.9", 6882), FakePeer("192.168.0.10", 6883)])
    handle = FakeHandle()

    attempted = reconnect_cached_peers(handle, store, "hashC")

    assert attempted == 2
    assert set(handle.connected) == {("192.168.0.9", 6882), ("192.168.0.10", 6883)}


def test_reconnect_cached_peers_is_a_noop_for_an_unknown_hash():
    store = LanPeerCacheStore()
    handle = FakeHandle()

    assert reconnect_cached_peers(handle, store, "unknown-hash") == 0
    assert handle.connected == []
