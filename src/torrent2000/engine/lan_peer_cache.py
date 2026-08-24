"""Opt-in local-network peer cache (catalogue "idees non implementees",
cluster Pairs & reseau du swarm) -- OFF BY DEFAULT (see
Settings.lan_peer_cache_enabled).

Remembers only peer IPs inside an RFC1918 private range (10.0.0.0/8,
172.16.0.0/12, 192.168.0.0/16) -- never anything routable/public -- keyed by
info_hash, so that re-adding a torrent already seen on this LAN can try to
reconnect those same local peers immediately via handle.connect_peer()
instead of waiting for tracker/DHT/LSD to rediscover them (useful e.g. right
after a relaunch, before LSD has had a chance to re-announce).

Fed from the same chokepoint as engine/peer_reputation.py --
SessionManager.get_peer_info(), the only two callers of which are
bridge_peer_list.py and bridge_swarm_constellation.py -- so entries only
accrue while something is already polling peer info (a peer list dialog or
the swarm view open); there is no separate background scanner.

Entries older than 48h are dropped lazily (on load, before every save, and
before every read) rather than with a dedicated purge timer.

Persistence follows the same tmp-file + os.replace() pattern as
engine/known_disk_service.py / engine/peer_reputation.py.

connect_peer's endpoint argument: confirmed via `help(lt.torrent_handle.
connect_peer)` against the installed build (libtorrent 2.0.13.0) and a live
call against a real session -- it takes a plain (str_ip, int_port) tuple
(source/flags left at their defaults), same tuple shape lt.peer_info.ip
already comes back as (see SessionManager.get_peer_info's own comment on
that).
"""

import ipaddress
import json
import logging
import os
import time
from dataclasses import asdict, dataclass

from torrent2000.config.paths import get_lan_peer_cache_path

logger = logging.getLogger(__name__)

MAX_AGE_SECONDS = 48 * 3600

_RFC1918_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def is_rfc1918(ip_str: str) -> bool:
    """True only for an address inside one of the three RFC1918 private
    ranges -- deliberately narrower than ipaddress.ip_address.is_private
    (which also flags loopback/link-local/CGNAT and various IPv6 ranges):
    this cache must never remember anything that could be a routable/public
    address. False (not raised) for anything unparseable."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in _RFC1918_NETWORKS)


@dataclass
class LanPeerRecord:
    ip: str
    port: int
    last_seen: float  # time.time() wall-clock epoch -- persisted, so this can't be time.monotonic()


class LanPeerCacheStore:
    """Persists, per info_hash, the set of RFC1918 peer (ip, port) pairs
    last seen for that torrent."""

    def __init__(self) -> None:
        # info_hash -> {ip: LanPeerRecord}
        self._entries: dict[str, dict[str, LanPeerRecord]] = {}
        self._load()

    def record_peers(self, info_hash: str, raw_peers) -> None:
        """raw_peers: the list returned by torrent_handle.get_peer_info() --
        duck-typed on .ip (an (address, port) tuple, same as
        peer_reputation.PeerReputationTracker.observe expects). Only
        RFC1918 addresses are kept; everything else is silently skipped."""
        now = time.time()
        by_ip = self._entries.setdefault(info_hash, {})
        changed = False
        for p in raw_peers:
            ip, port = p.ip
            ip = str(ip)
            if not is_rfc1918(ip):
                continue
            by_ip[ip] = LanPeerRecord(ip=ip, port=int(port), last_seen=now)
            changed = True
        if not changed:
            return
        self._purge_expired()
        self._save()

    def get_peers(self, info_hash: str) -> list[tuple[str, int]]:
        """(ip, port) pairs currently cached for this info_hash. Purges
        expired entries first so a read never returns a stale (>48h) peer."""
        self._purge_expired()
        return [(rec.ip, rec.port) for rec in self._entries.get(info_hash, {}).values()]

    # ------------------------------------------------------------- internal

    def _purge_expired(self) -> None:
        cutoff = time.time() - MAX_AGE_SECONDS
        for info_hash in list(self._entries):
            by_ip = self._entries[info_hash]
            for ip in list(by_ip):
                if by_ip[ip].last_seen < cutoff:
                    del by_ip[ip]
            if not by_ip:
                del self._entries[info_hash]

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        path = get_lan_peer_cache_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        data = {
            info_hash: {ip: asdict(rec) for ip, rec in by_ip.items()} for info_hash, by_ip in self._entries.items()
        }
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_lan_peer_cache_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return  # malformed top-level shape -- start empty rather than crash on startup
        for info_hash, by_ip in data.items():
            if not isinstance(by_ip, dict):
                continue
            entries: dict[str, LanPeerRecord] = {}
            for ip, entry in by_ip.items():
                try:
                    entries[ip] = LanPeerRecord(**entry)
                except TypeError:
                    continue  # malformed/outdated entry -- skip rather than crash on startup
            if entries:
                self._entries[info_hash] = entries
        self._purge_expired()


def reconnect_cached_peers(handle, store: LanPeerCacheStore, info_hash: str) -> int:
    """Calls handle.connect_peer((ip, port)) for every LAN peer this store
    remembers for info_hash -- meant to be called right after a torrent
    already seen on this LAN before is re-added, ahead of tracker/DHT/LSD
    rediscovering it on their own. Best-effort: connect_peer only queues a
    connection attempt, so a now-offline/stale entry is harmless and not
    removed here for that alone. Returns how many attempts were made."""
    count = 0
    for ip, port in store.get_peers(info_hash):
        try:
            handle.connect_peer((ip, port))
            count += 1
        except Exception:
            logger.exception("lan_peer_cache: connect_peer failed for %s:%s", ip, port)
    return count


def _demo() -> None:
    """Smallest runnable self-check -- not a pytest suite. Run directly:
    python -m torrent2000.engine.lan_peer_cache
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["TORRENT2000_DATA_DIR"] = tmp_dir

        # --- RFC1918 filter ---------------------------------------------
        assert is_rfc1918("10.0.0.1") is True
        assert is_rfc1918("172.16.0.1") is True
        assert is_rfc1918("172.31.255.255") is True
        assert is_rfc1918("192.168.1.1") is True
        assert is_rfc1918("172.32.0.1") is False  # just outside the 172.16.0.0/12 block
        assert is_rfc1918("172.15.255.255") is False  # just below it
        assert is_rfc1918("8.8.8.8") is False  # public
        assert is_rfc1918("127.0.0.1") is False  # loopback, not RFC1918
        assert is_rfc1918("169.254.1.1") is False  # link-local, not RFC1918
        assert is_rfc1918("fe80::1") is False  # IPv6 entirely out of scope here
        assert is_rfc1918("not-an-ip") is False  # never raises

        class _FakePeer:
            def __init__(self, ip, port):
                self.ip = (ip, port)

        class _FakeHandle:
            def __init__(self):
                self.connected: list[tuple[str, int]] = []

            def connect_peer(self, endpoint):
                self.connected.append(endpoint)

        store = LanPeerCacheStore()
        assert store.get_peers("hashA") == []

        # public + private peers mixed in one observation -- only the
        # private one should survive
        store.record_peers("hashA", [_FakePeer("8.8.8.8", 6881), _FakePeer("192.168.1.50", 51413)])
        assert store.get_peers("hashA") == [("192.168.1.50", 51413)]

        # a second store instance loading the same path sees the persisted entry
        reloaded = LanPeerCacheStore()
        assert reloaded.get_peers("hashA") == [("192.168.1.50", 51413)]

        # --- 48h purge ----------------------------------------------------
        stale_store = LanPeerCacheStore()
        stale_store.record_peers("hashB", [_FakePeer("10.1.2.3", 6881)])
        # backdate the entry past the 48h cutoff directly, rather than
        # sleeping in a test
        stale_store._entries["hashB"]["10.1.2.3"].last_seen = time.time() - MAX_AGE_SECONDS - 1
        assert stale_store.get_peers("hashB") == []  # purged lazily on read
        assert "hashB" not in stale_store._entries  # emptied dict is dropped entirely

        # --- reconnect on add ---------------------------------------------
        store.record_peers("hashC", [_FakePeer("192.168.0.9", 6882), _FakePeer("192.168.0.10", 6883)])
        handle = _FakeHandle()
        attempted = reconnect_cached_peers(handle, store, "hashC")
        assert attempted == 2
        assert set(handle.connected) == {("192.168.0.9", 6882), ("192.168.0.10", 6883)}

        # a torrent with nothing cached yet reconnects to nothing, no error
        assert reconnect_cached_peers(handle, store, "unknown-hash") == 0

    print("lan_peer_cache self-check OK")


if __name__ == "__main__":
    _demo()
