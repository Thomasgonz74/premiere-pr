"""Opt-in local peer reputation tracking (catalogue "idees non implementees",
cluster Pairs & reseau du swarm) -- OFF BY DEFAULT (see
Settings.peer_reputation_enabled).

For each peer IP encountered, journals two things once the setting is on:
  - connection stability: average seconds a connection to that IP stays up
    before it's observed to drop
  - data actually received from that IP, and how much of it turned out bad

libtorrent's peer_info (this build, 2.0.13.0 -- checked via dir(lt.peer_info)
and help(lt.peer_info) rather than guessed) exposes no "connected since"
timestamp and no literal "valid blocks received" counter. The closest fields
actually available are used instead:
  - total_download: cumulative payload bytes received on the CURRENT
    connection. This resets to 0 if the peer reconnects, so it has to be
    read right before a disconnect and folded into a persisted running
    total -- it is not a stable absolute counter across reconnects.
  - num_hashfails: cumulative count of pieces from this peer that failed the
    hash check on the CURRENT connection (same reset-on-reconnect caveat).
    This is the actual "bad data" signal -- total_download alone doesn't
    distinguish valid payload from corrupt payload that got discarded.

Connection duration is derived here, not read from libtorrent: this module
is fed directly from SessionManager.get_peer_info(), the one chokepoint all
peer_info already flows through (its only two callers are
bridge_peer_list.py and bridge_swarm_constellation.py) -- a peer present on
one observation and absent on the next is treated as having disconnected in
between. There is no separate background timer polling every torrent's
peers on its own; reputation only accrues while something is already
polling peer info (a peer list dialog or the swarm view open).

Persistence follows the same tmp-file + os.replace() pattern as
engine/known_disk_service.py.
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass

from torrent2000.config.paths import get_peer_reputation_path

logger = logging.getLogger(__name__)


def _ip_key(raw_ip) -> str:
    """raw_ip is the (address, port) tuple from lt.peer_info.ip -- keyed by
    address only, so the same peer machine reconnecting on a different port
    is still recognized as the same peer."""
    return str(raw_ip[0])


def ip_from_display(display_ip: str) -> str:
    """The UI-facing peer IP (PeerInfo.ip / bridge_peer_list.js's peer.ip) is
    formatted as "address:port" (see SessionManager.get_peer_info). Split off
    the port to get the same address-only key _ip_key() stores under.
    rsplit on the LAST colon works for IPv6 addresses too (however many
    colons the address itself has, the port is always after the final one)."""
    return display_ip.rsplit(":", 1)[0]


@dataclass
class PeerReputationRecord:
    ip: str
    disconnect_count: int = 0  # number of completed connection streaks folded in so far
    total_connected_seconds: float = 0.0
    total_bytes_received: int = 0  # sum of total_download at disconnect, across streaks (see module docstring)
    total_hashfails: int = 0  # sum of num_hashfails at disconnect, across streaks


class PeerReputationStore:
    """Persists per-IP reputation records to disk as JSON."""

    def __init__(self) -> None:
        self._records: dict[str, PeerReputationRecord] = {}
        self._load()

    def get(self, ip: str) -> PeerReputationRecord | None:
        return self._records.get(ip)

    def record_disconnect(self, ip: str, connected_seconds: float, bytes_received: int, hashfails: int) -> None:
        rec = self._records.get(ip)
        if rec is None:
            rec = PeerReputationRecord(ip=ip)
            self._records[ip] = rec
        rec.disconnect_count += 1
        rec.total_connected_seconds += connected_seconds
        rec.total_bytes_received += bytes_received
        rec.total_hashfails += hashfails
        self._save()

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        # ponytail: writes to disk on every peer disconnect -- fine at
        # hobby-app peer counts; debounce/batch if heavy swarm churn while
        # the peer dialog is open ever makes this measurably slow.
        path = get_peer_reputation_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        data = {ip: asdict(rec) for ip, rec in self._records.items()}
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_peer_reputation_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return  # malformed top-level shape -- start empty rather than crash on startup
        for ip, entry in data.items():
            try:
                self._records[ip] = PeerReputationRecord(**entry)
            except TypeError:
                continue  # malformed/outdated entry -- skip rather than crash on startup


class PeerReputationTracker:
    """Turns repeated get_peer_info() snapshots into disconnect events fed to
    a PeerReputationStore. See module docstring for why duration/bytes are
    derived here instead of being read directly from libtorrent.

    ponytail: a connection streak still active when polling simply stops
    (dialog closed, app quit) never gets folded into the persisted totals --
    only a clean "seen last tick, gone this tick" transition counts as a
    disconnect. Upgrade: flush self._active through record_disconnect() from
    a shutdown hook if exhaustive accounting is ever needed.
    """

    def __init__(self, store: PeerReputationStore) -> None:
        self._store = store
        # (info_hash, ip) -> (first_seen_monotonic, last_total_download, last_num_hashfails)
        self._active: dict[tuple[str, str], tuple[float, int, int]] = {}

    def observe(self, info_hash: str, raw_peers) -> None:
        """raw_peers: the list returned by torrent_handle.get_peer_info() --
        duck-typed on .ip/.total_download/.num_hashfails rather than
        importing libtorrent here."""
        now = time.monotonic()
        seen_keys = set()
        for p in raw_peers:
            ip = _ip_key(p.ip)
            seen_keys.add(ip)
            key = (info_hash, ip)
            first_seen, _, _ = self._active.get(key, (now, 0, 0))
            self._active[key] = (first_seen, p.total_download, p.num_hashfails)

        # any (info_hash, ip) active before this tick but absent now has disconnected
        gone = [key for key in self._active if key[0] == info_hash and key[1] not in seen_keys]
        for key in gone:
            first_seen, total_download, num_hashfails = self._active.pop(key)
            self._store.record_disconnect(key[1], now - first_seen, total_download, num_hashfails)


def score_label(record: PeerReputationRecord | None) -> str:
    """Coarse "good" | "neutral" | "bad" badge for a peer reputation record.
    "neutral" also covers peers with no completed connection streak yet --
    not enough data for a verdict either way.

    ponytail: naive fixed thresholds (60s min average duration, any hashfail
    = bad); tune once real usage data exists.
    """
    if record is None or record.disconnect_count == 0:
        return "neutral"
    if record.total_hashfails > 0:
        return "bad"
    avg_duration = record.total_connected_seconds / record.disconnect_count
    if avg_duration >= 60 and record.total_bytes_received > 0:
        return "good"
    return "neutral"


def _demo() -> None:
    """Smallest runnable self-check -- not a pytest suite. Run directly:
    python -m torrent2000.engine.peer_reputation
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["TORRENT2000_DATA_DIR"] = tmp_dir

        store = PeerReputationStore()
        assert store.get("1.2.3.4") is None
        assert score_label(store.get("1.2.3.4")) == "neutral"

        tracker = PeerReputationTracker(store)

        class _FakePeer:
            def __init__(self, ip, port, total_download, num_hashfails):
                self.ip = (ip, port)
                self.total_download = total_download
                self.num_hashfails = num_hashfails

        # peer connects (seen once)...
        tracker.observe("hashA", [_FakePeer("1.2.3.4", 6881, 1000, 0)])
        assert store.get("1.2.3.4") is None  # still active, no disconnect folded in yet
        # ...then disconnects (absent from the next snapshot)
        tracker.observe("hashA", [])
        rec = store.get("1.2.3.4")
        assert rec is not None
        assert rec.disconnect_count == 1
        assert rec.total_bytes_received == 1000
        assert rec.total_hashfails == 0

        # a peer that sent bad data should score "bad" regardless of duration
        tracker.observe("hashA", [_FakePeer("5.6.7.8", 6881, 500, 3)])
        tracker.observe("hashA", [])
        assert score_label(store.get("5.6.7.8")) == "bad"

        # a second store instance loading the same path should see the persisted data
        reloaded = PeerReputationStore()
        assert reloaded.get("1.2.3.4").total_bytes_received == 1000

        # different info_hash tracking the same IP shouldn't cross-contaminate disconnects
        tracker.observe("hashB", [_FakePeer("9.9.9.9", 6881, 10, 0)])
        tracker.observe("hashA", [])  # unrelated torrent's tick -- 9.9.9.9 on hashB must stay active
        assert ("hashB", "9.9.9.9") in tracker._active

        # ip_from_display strips the port even for an IPv6-shaped address
        assert ip_from_display("203.0.113.7:6881") == "203.0.113.7"
        assert ip_from_display("fe80::1:6881") == "fe80::1"

    print("peer_reputation self-check OK")


if __name__ == "__main__":
    _demo()
