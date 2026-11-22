import collections
import json
import logging
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

import libtorrent as lt
from PySide6.QtCore import QCoreApplication, QObject, QThreadPool, QTimer, Signal

from torrent2000 import APP_VERSION
from torrent2000.config.paths import (
    get_awaiting_analysis_path,
    get_default_download_dir,
    get_magnets_to_start_path,
    get_matched_rules_path,
)
from torrent2000.config.settings import Settings
from torrent2000.engine import add_params, persistence, proxy, trackers as tracker_ops
from torrent2000.engine.alerts import AlertDispatcher, _hash_of, status_to_record
from torrent2000.engine.lan_peer_cache import LanPeerCacheStore, reconnect_cached_peers
from torrent2000.engine.ip_blocklist import BlocklistLoadRunnable, BlocklistSignals
from torrent2000.engine.peer_reputation import PeerReputationStore, PeerReputationTracker, ip_from_display, score_label
from torrent2000.engine.torrent_categories import TorrentCategoryService
from torrent2000.engine.torrent_item import ACTIVE_DOWNLOAD_STATES, PeerInfo, TorrentRecord, TorrentState, TrackerInfo
from torrent2000.i18n.translator import tr
from torrent2000.theme_ids import CCCP_THEME_ID
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

FILE_PRIORITY_EXCLUDED = 0
FILE_PRIORITY_DEFAULT = 4

# Deadline-based queue priority (see SessionManager._apply_deadline_priorities):
# a torrent only starts climbing the queue once its deadline is within this
# many seconds, and the sweep itself only runs this often -- piggybacked on
# the existing 300ms _on_tick, but running the actual comparison/queue-move
# work on every single tick would be pure waste for something that only
# matters at hour granularity.
DEADLINE_URGENT_WINDOW_S = 24 * 3600
_DEADLINE_SWEEP_INTERVAL_S = 10.0

# Streaming (see set_sequential_download): how many pieces at the head of
# the largest file get an urgency deadline, and how far apart (in ms) each
# successive one's deadline is set -- a real player only ever needs a
# rolling window near its current playback position, not the whole file.
_STREAMING_HEAD_PIECE_COUNT = 30
_STREAMING_DEADLINE_STEP_MS = 500

# Periodic autosave (see _save_all_resume_data): how many queued
# save_resume_data() calls _on_tick posts per 300ms tick. Each one comes
# back as a save_resume_data_alert costing ~3-5 ms of GUI-thread work
# (handle.status() + atomic file write), so the whole batch is spread over
# ticks instead of landing in a single pop_alerts() burst.
_RESUME_SAVES_PER_TICK = 2

# Session restore (see _bind_restored_handles): how often the alerts are
# dispatched, between ticks, until every restored torrent has its handle.
_RESTORE_BIND_POLL_MS = 20

# post_torrent_updates() flags. Without an argument libtorrent uses
# 0xFFFFFFFF, which also walks every piece to copy two bitfields and compute
# distributed_copies per changed torrent, on every tick, for fields
# status_to_record never reads. 64 (query_name) and 128 (query_save_path)
# are raw literals because the 2.0.13 Python bindings don't expose them;
# without query_name a magnet's name never fills in once metadata arrives,
# and without query_save_path status.save_path comes back empty.
_STATUS_UPDATE_FLAGS = int(lt.torrent_handle.query_accurate_download_counters) | 64 | 128

_CHECKING_STATES = (lt.torrent_status.checking_files, lt.torrent_status.checking_resume_data)

ALERT_MASK = (
    lt.alert_category.error
    | lt.alert_category.status
    | lt.alert_category.storage
    | lt.alert_category.tracker
    | lt.alert_category.peer
)


# libtorrent enc_policy/enc_level values for this installed build (2.0.13.0):
# enc_policy.forced=0, enabled=1, disabled=2; enc_level.plaintext=1, rc4=2,
# both=3. "forced" refuses plaintext outright (int(lt.enc_level.rc4)) as an
# anti-ISP-throttling measure; "enabled" (libtorrent's own default) and
# "disabled" both allow the full negotiation range since they don't need to
# forbid plaintext, they just prefer/skip encryption respectively.
_ENCRYPTION_POLICY_MAP = {
    "forced": (int(lt.enc_policy.forced), int(lt.enc_level.rc4)),
    "enabled": (int(lt.enc_policy.enabled), int(lt.enc_level.both)),
    "disabled": (int(lt.enc_policy.disabled), int(lt.enc_level.both)),
}


def _write_provenance_manifest(record: TorrentRecord) -> None:
    """Writes a "<info_hash>.provenance.json" manifest next to a finished
    torrent's downloaded files (opt-in, see Settings.provenance_manifest_enabled
    and SessionManager._on_torrent_finished). Defensive: a failed write (e.g.
    save_path no longer exists, permissions) is logged, never raised -- the
    manifest is a nice-to-have, not something that should break torrent
    completion handling.
    """
    completed_at = record.completed_at or time.time()
    manifest = {
        "info_hash": record.info_hash,
        "name": record.name,
        "completed_at": datetime.fromtimestamp(completed_at, tz=timezone.utc).isoformat(),
        "trackers": [tracker.url for tracker in record.trackers],
        "total_size": record.total_size,
    }
    path = Path(record.save_path) / f"{record.info_hash}.provenance.json"
    try:
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.exception("Failed to write provenance manifest for %s", record.info_hash)


def _is_download_start_blocked(theme_id: str, progress: float) -> bool:
    """True when the active theme's "no downloading" rule (currently just
    CCCP -- "on est là pour partager, pas posséder") refuses to start or
    resume a torrent at this progress. A torrent already at 100% is pure
    seeding, which every theme allows -- sharing is the whole point."""
    return theme_id == CCCP_THEME_ID and progress < 1.0


def _encryption_settings_fragment(mode: str) -> dict:
    policy, level = _ENCRYPTION_POLICY_MAP.get(mode, _ENCRYPTION_POLICY_MAP["enabled"])
    return {
        "out_enc_policy": policy,
        "in_enc_policy": policy,
        "allowed_enc_level": level,
    }


def _build_session_settings(settings: Settings) -> dict:
    base = lt.default_settings()
    base.update(
        {
            "alert_mask": ALERT_MASK,
            "active_downloads": settings.max_active_downloads,
            "active_seeds": settings.max_active_downloads,
            # libtorrent's own default is 1 -- only ONE auto-managed torrent,
            # session-wide, may occupy the "checking files" slot at a time.
            # Every torrent added via the Partage tab has to pass through
            # this check (it's already on disk, libtorrent must verify it)
            # before it can start seeding, so leaving this at the default
            # made a second share sit paused/stuck at 0% until the first
            # one's check finished -- looking exactly like "can't share two
            # torrents at once".
            "active_checking": settings.max_active_downloads,
            "active_limit": settings.max_active_downloads * 2,
            "user_agent": f"Torrent2000/{APP_VERSION}",
            "download_rate_limit": settings.download_rate_limit_kbps * 1024,
            "upload_rate_limit": settings.upload_rate_limit_kbps * 1024,
            # Zero-config privacy hardening, active from the very first launch
            # (no user action required). "anonymous_mode" trims identifying
            # information (e.g. resets the user agent sent to trackers/peers)
            # -- it does NOT and cannot hide the client's IP from the peers it
            # directly connects to; only a user-supplied proxy/VPN (below) can
            # do that, since BitTorrent is a direct peer-to-peer protocol.
            "anonymous_mode": True,
        }
    )
    if settings.restrict_discovery:
        # DHT and LSD are broadcast/discovery mechanisms: DHT in particular
        # publishes this client's IP into a global public DHT network of many
        # thousands of nodes, far beyond the peers it is actually exchanging
        # data with. Disabling them at the session level is a genuine,
        # zero-relay reduction in IP exposure. (PEX has no session-wide
        # on/off switch in this libtorrent build; it is disabled per-torrent
        # instead -- see engine/add_params.py.)
        base.update(
            {
                "enable_dht": False,
                "enable_lsd": False,
            }
        )
    base.update(proxy.build_settings_fragment(settings.proxy))
    if settings.network_interface:
        base.update(proxy.build_interface_fragment(settings.network_interface))
    base.update(_encryption_settings_fragment(settings.encryption_mode))
    return base


_DENIED_MOVE_ROOTS: list[Path] | None = None


def _denied_move_roots() -> list[Path]:
    """Sensitive system directories a torrent's files must never be
    relocated into -- resolved once from the real environment (not
    hardcoded drive letters, so this still works on a non-C: Windows
    install). Cached at module scope since these never change during a
    process's lifetime."""
    global _DENIED_MOVE_ROOTS
    if _DENIED_MOVE_ROOTS is None:
        candidates = [
            os.environ.get("SystemRoot"),
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("ProgramData"),
        ]
        _DENIED_MOVE_ROOTS = [Path(c).resolve() for c in candidates if c]
    return _DENIED_MOVE_ROOTS


def is_safe_move_destination(new_path: str) -> bool:
    """Defense in depth for move_storage(): the legitimate caller
    (downloads.js) always gets new_path from a native folder picker, but
    the web bridge slot it calls through has no way to tell a real user
    choice from a compromised/malicious JS call -- refuse a bare drive
    root, a UNC/network path, and a handful of sensitive system
    directories regardless of who's asking."""
    try:
        resolved = Path(new_path).resolve()
    except (OSError, ValueError):
        return False
    if str(resolved).startswith("\\\\"):
        return False
    if resolved.parent == resolved:  # a filesystem root has itself as parent
        return False
    for denied in _denied_move_roots():
        if resolved == denied or denied in resolved.parents:
            return False
    return True


def _is_confined(file_path: Path, resolved_root: Path) -> bool:
    """True if file_path resolves to somewhere under resolved_root (the
    torrent's save_path, already resolved) -- guards lock/unlock/
    get_allocated_size against a torrent whose internal file paths were
    crafted with a `../` segment or an absolute path, which would otherwise
    let them touch a file outside the intended download directory. Same
    resolve-then-contains check as is_safe_move_destination above, applied
    here to a path built from torrent-internal metadata rather than a
    user-chosen destination. The root is resolved once by the caller, not
    per file: each resolve() opens an NT handle (~1.8 ms), which added up
    to seconds on a 1000-file torrent."""
    try:
        resolved = file_path.resolve()
    except (OSError, ValueError):
        return False
    return resolved == resolved_root or resolved_root in resolved.parents


class TorrentAlreadyPresentError(ValueError):
    def __init__(self, info_hash: str) -> None:
        super().__init__(tr("add_tab.duplicate_message"))
        self.info_hash = info_hash


class SessionManager(QObject):
    torrent_added = Signal(str)
    torrent_removed = Signal(str)
    # libtorrent refused a torrent restored from the previous session: its
    # row must go, but unlike torrent_removed nothing about it is forgotten
    # -- its .fastresume, tags, category and share limit wait for next launch.
    torrent_restore_failed = Signal(str)
    torrent_status_updated = Signal(str, object)  # str info_hash, TorrentRecord
    # Emitted once per status tick, after every torrent_status_updated of
    # that tick: list[TorrentRecord]. Lets the web bridges push one
    # QWebChannel message per tick instead of one per torrent.
    torrent_status_batch_updated = Signal(list)
    torrent_finished = Signal(str)
    metadata_received = Signal(str)
    tracker_error = Signal(str, str)
    # The CCCP theme's "no downloading, only sharing" rule refused to start
    # or resume this not-yet-complete torrent (str info_hash).
    download_blocked_by_theme = Signal(str)
    # Switching TO the CCCP theme paused this many still-downloading
    # torrents outright (see enforce_theme_download_policy).
    theme_downloads_paused = Signal(int)
    storage_moved = Signal(str, str)  # str info_hash, str new_path
    move_storage_refused = Signal(str, str)  # str info_hash, str refused path
    storage_move_failed = Signal(str, str)  # str info_hash, str error message
    # A disk/file I/O error (e.g. an external drive dropping out mid-write)
    # paused this torrent automatically. str info_hash, str error message.
    file_error = Signal(str, str)
    # True while the session is held paused for the IP blocklist, False once
    # the filter is applied or the load ended (see _load_ip_blocklist).
    ip_blocklist_wait_changed = Signal(bool)

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        session_settings = _build_session_settings(settings)
        # Kept for _restore_previous_session: reading it back from the session
        # (get_settings) would be a blocking round trip to the network thread.
        self._alert_queue_floor = session_settings.get("alert_queue_size", lt.default_settings()["alert_queue_size"])
        self._session = lt.session(session_settings)
        # See _load_ip_blocklist -- True only while the session is paused by
        # that code, so it never resumes a pause it didn't make.
        self._paused_for_ip_blocklist = False
        if settings.ip_blocklist_enabled and settings.ip_blocklist_path:
            self._load_ip_blocklist(settings.ip_blocklist_path)
        self._records: dict[str, TorrentRecord] = {}
        self._handles: dict[str, "lt.torrent_handle"] = {}
        self._private_flag_checked: set[str] = set()
        # info_hashes restored from resume data whose check hasn't ended yet
        # -- see _on_torrent_finished. libtorrent re-fires
        # torrent_finished_alert for a complete one while verifying its
        # fast-resume data on every restart, even though nothing was actually
        # (re)downloaded this session. Same for a recheck of a complete
        # torrent, or a share of data already on disk (see expect_existing_data).
        self._pending_restore_confirmation: set[str] = set()
        # Resumed (or left running) under CCCP while being checked: resumed
        # once checked if the check found the data complete -- see
        # _resume_once_checked.
        self._resume_after_check: set[str] = set()
        # info_hashes queued by _restore_previous_session's async_add_torrent
        # whose add_torrent_alert hasn't arrived yet -- see _on_torrent_added.
        self._pending_restore: set[str] = set()
        # Magnets still waiting for start_after_analysis, saved so a restart
        # brings them back awaiting it (their upload mode is in the resume data).
        self._awaiting_analysis: set[str] = {
            h for h in persistence.load_json(get_awaiting_analysis_path(), []) if isinstance(h, str)
        }
        # add_torrent_from_magnet's save, made once per event-loop pass: an RSS
        # check adding a hundred magnets writes the file once, not a hundred times.
        self._awaiting_save_queued = False
        # Those of them the user started from the Downloads page before their
        # metadata was in -- see start_awaiting_magnet.
        self._start_once_analysed: set[str] = {
            h for h in persistence.load_json(get_magnets_to_start_path(), [])
            if isinstance(h, str) and h in self._awaiting_analysis
        }
        # info_hash -> TorrentRecord.matched_rule_name, saved so a download
        # that spans a restart still gets its rule's post-complete action.
        self._matched_rules: dict[str, str] = {
            h: name for h, name in persistence.load_json(get_matched_rules_path(), {}).items() if isinstance(name, str)
        }
        # info_hashes whose pending move is move_storage(quiet=True): see there.
        self._quiet_moves: set[str] = set()
        self._categories = TorrentCategoryService()
        # In-memory only (not persisted): ~60s of (download_rate, upload_rate)
        # samples per torrent at this timer's 300ms tick, for the speed-over-
        # time graph. maxlen=200 caps memory use per torrent and keeps the
        # deque self-trimming -- oldest sample drops as a new one arrives.
        self._speed_history: dict[str, collections.deque] = {}
        # Opt-in (see Settings.peer_reputation_enabled) -- constructed
        # unconditionally since it's cheap (one small JSON file) and just
        # sits idle unless the setting is on, same convention as the other
        # *_enabled flags checked at call time rather than at construction.
        self._peer_reputation_store = PeerReputationStore()
        self._peer_reputation_tracker = PeerReputationTracker(self._peer_reputation_store)
        # Opt-in (see Settings.lan_peer_cache_enabled) -- same "cheap, sits
        # idle unless the setting is on" construction convention as the peer
        # reputation store above.
        self._lan_peer_cache_store = LanPeerCacheStore()
        # Both stores above throttle their disk writes to one per 30 s --
        # write whatever is still pending when the app quits. Hooked here,
        # where the stores live, not in run_web_spike.py's _shutdown.
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._flush_peer_stores)
        # time.time() of the last deadline-priority sweep -- see
        # _apply_deadline_priorities, throttling that work inside _on_tick.
        self._last_deadline_sweep = 0.0
        # info_hashes waiting for their periodic autosave -- filled by
        # _save_all_resume_data, drained by _drain_resume_save_queue.
        self._resume_save_queue: collections.deque[str] = collections.deque()

        self._dispatcher = AlertDispatcher(
            on_state_update=self._on_state_update,
            on_metadata_received=self._on_metadata_received,
            on_torrent_finished=self._on_torrent_finished,
            on_torrent_checked=self._on_torrent_checked,
            on_tracker_error=self._on_tracker_error,
            on_save_resume_data=self._on_save_resume_data,
            on_torrent_removed=self._on_torrent_removed,
            on_torrent_added=self._on_torrent_added,
            on_storage_moved=self._on_storage_moved,
            on_storage_move_failed=self._on_storage_move_failed,
            on_file_error=self._on_file_error,
        )

        self._timer = start_periodic_timer(self, 300, self._on_tick)

        # shutdown() (MainWindow.closeEvent) is the main save point, but
        # relying on it alone means an abnormal exit -- a crash, a killed
        # process, a power loss -- loses every torrent added since the last
        # clean close. This periodic save is the same save_resume_data()/
        # save_resume_data_alert pipeline shutdown() already uses, just
        # triggered on a timer instead of only at exit.
        self._resume_save_timer = start_periodic_timer(self, 120_000, self._save_all_resume_data)

        self._restore_previous_session()
        QTimer.singleShot(0, self, self._bind_restored_handles)

    def _load_ip_blocklist(self, path: str) -> None:
        """Parses the blocklist on a QThreadPool worker instead of blocking
        startup for seconds. Torrents must not reach a single peer before
        the filter is in place, so the whole session (every torrent, and
        incoming connections) stays paused until _on_ip_blocklist_loaded
        runs back on the GUI thread -- also when the file turns out to be
        missing or unreadable, in which case it resumes without a filter.
        Only called from __init__, on a session that can't be paused yet:
        no is_paused() check, a blocking round trip to the network thread."""
        self._session.pause()
        self._paused_for_ip_blocklist = True
        logger.info("IP blocklist: session paused until %r is parsed", path)
        self.ip_blocklist_wait_changed.emit(True)
        self._ip_blocklist_signals = BlocklistSignals()
        self._ip_blocklist_signals.loaded.connect(self._on_ip_blocklist_loaded)
        QThreadPool.globalInstance().start(BlocklistLoadRunnable(path, self._ip_blocklist_signals))

    def _on_ip_blocklist_loaded(self, ip_filter) -> None:
        # shutdown() stops the tick timer first; this can still be delivered
        # by its event pumping, and must not resume the session then.
        if not self._timer.isActive():
            return
        if ip_filter is not None:
            self._session.set_ip_filter(ip_filter)
        if self._paused_for_ip_blocklist:
            self._paused_for_ip_blocklist = False
            self._session.resume()
            logger.info("IP blocklist: %s, session resumed", "filter applied" if ip_filter is not None else "no filter")
            self.ip_blocklist_wait_changed.emit(False)

    def is_waiting_for_ip_blocklist(self) -> bool:
        """For a page that loads after the wait began (the pause happens in
        __init__, before any bridge is connected)."""
        return self._paused_for_ip_blocklist

    # ------------------------------------------------------------------ tick

    def _on_tick(self) -> None:
        self._session.post_torrent_updates(_STATUS_UPDATE_FLAGS)
        self._dispatch_alerts()
        self._apply_deadline_priorities()
        self._drain_resume_save_queue()

    def _dispatch_alerts(self) -> None:
        alerts = self._session.pop_alerts()
        if alerts:
            self._dispatcher.dispatch_all(alerts)

    def _bind_restored_handles(self) -> None:
        """From the first pass of the event loop, not the first 300 ms tick:
        dispatches libtorrent's alerts every _RESTORE_BIND_POLL_MS until each
        restored torrent's add_torrent_alert has bound its handle, so an
        action on it works as soon as libtorrent has added it. pop_alerts()
        doesn't wait on the network thread: never blocks, even while it
        stalls."""
        if not self._pending_restore or not self._timer.isActive():
            return  # all bound, or shutdown() has started
        self._dispatch_alerts()
        if self._pending_restore:
            QTimer.singleShot(_RESTORE_BIND_POLL_MS, self, self._bind_restored_handles)

    def _apply_deadline_priorities(self) -> None:
        """Deadline queue priority: a torrent with record.deadline set gets
        bumped up the queue (via move_queue_up/queue_position_up) as that
        deadline approaches, faster the closer/more overdue it is. Only
        touches torrents actually in the download queue (ACTIVE_DOWNLOAD_STATES)
        -- bumping a paused/seeding/finished torrent's queue position would
        be meaningless. Throttled to _DEADLINE_SWEEP_INTERVAL_S despite
        running inside the 300ms _on_tick -- see DEADLINE_URGENT_WINDOW_S."""
        now = time.time()
        if now - self._last_deadline_sweep < _DEADLINE_SWEEP_INTERVAL_S:
            return
        self._last_deadline_sweep = now
        for info_hash, record in self._records.items():
            if record.deadline is None or record.state not in ACTIVE_DOWNLOAD_STATES:
                continue
            remaining = record.deadline - now
            if remaining > DEADLINE_URGENT_WINDOW_S:
                continue  # deadline not approaching yet
            # 0.0 (just entered the urgent window) .. 1.0 (deadline reached
            # or already passed) -- an overdue deadline is clamped to full
            # urgency rather than skipped, since it's still the most urgent
            # thing to finish.
            urgency = 1.0 - max(remaining, 0.0) / DEADLINE_URGENT_WINDOW_S
            steps = 1 + round(urgency * 4)  # 1..5 queue_position_up() calls this sweep
            handle = self._handles.get(info_hash)
            if handle is None:
                continue
            for _ in range(steps):
                handle.queue_position_up()

    def _save_all_resume_data(self) -> None:
        # Only queues the saves: _on_tick posts _RESUME_SAVES_PER_TICK of
        # them per tick, so e.g. 200 torrents' resume writes are spread over
        # ~30 s instead of freezing the GUI thread for 0.5-1 s in one block
        # every 2 minutes. Trade-off: the crash-loss window for the last
        # torrent in the queue grows from 120 s to about 150-180 s.
        # Hashes still queued from the previous round aren't re-added, so a
        # queue that hasn't finished draining (800+ torrents) just carries on.
        queued = set(self._resume_save_queue)
        self._resume_save_queue.extend(ih for ih in self._handles if ih not in queued)

    def _drain_resume_save_queue(self) -> None:
        for _ in range(min(_RESUME_SAVES_PER_TICK, len(self._resume_save_queue))):
            # Re-checked at pop time, not at queue time: the torrent may have
            # been removed (or its handle invalidated) since the queue filled.
            handle = self._handles.get(self._resume_save_queue.popleft())
            if handle is not None and handle.is_valid():
                # only_if_modified skips torrents whose state hasn't changed
                # since their last save (in practice mostly paused ones).
                handle.save_resume_data(lt.torrent_handle.save_info_dict | lt.torrent_handle.only_if_modified)

    # ------------------------------------------------------------- alert cbs

    def _on_state_update(self, status_list: list) -> None:
        updated: list[TorrentRecord] = []
        try:
            for status in status_list:
                info_hash = _hash_hex(status.info_hashes)
                record = self._records.get(info_hash)
                if record is None:
                    continue
                status_to_record(status, record)
                history = self._speed_history.get(info_hash)
                if history is None:
                    history = collections.deque(maxlen=200)
                    self._speed_history[info_hash] = history
                history.append((record.download_rate, record.upload_rate))
                if info_hash not in self._private_flag_checked:
                    # handle.torrent_file() returns None until metadata has
                    # actually arrived, so this can't be done once at add time --
                    # poll for it lazily here instead, and stop polling as soon
                    # as it's been resolved once (whatever the result).
                    handle = self._handles.get(info_hash)
                    ti = handle.torrent_file() if handle is not None and handle.is_valid() else None
                    if ti is not None:
                        record.is_private = ti.priv()
                        self._private_flag_checked.add(info_hash)
                self.torrent_status_updated.emit(info_hash, record)
                updated.append(record)
        finally:
            # In a finally so an exception mid-loop doesn't hold back the
            # torrents already processed this tick.
            if updated:
                self.torrent_status_batch_updated.emit(updated)

    def _on_metadata_received(self, info_hash: str) -> None:
        record = self._records.get(info_hash)
        if record is not None:
            record.is_magnet_awaiting_metadata = False
        self.metadata_received.emit(info_hash)
        if info_hash in self._start_once_analysed:
            self._start_once_analysed.discard(info_hash)
            self._save_start_once_analysed()
            if record is not None and record.awaiting_analysis:  # not started meanwhile (RSS, Add page...)
                self._scan_and_start(info_hash)

    def _on_torrent_finished(self, info_hash: str) -> None:
        if info_hash in self._pending_restore_confirmation:
            # Not a new completion -- libtorrent re-emits this alert while
            # verifying a restored torrent's fast-resume data confirms it's
            # still 100% present on disk. Swallow the one-shot reconfirmation
            # so it doesn't reach NotificationService as a "download
            # finished" toast on every relaunch.
            self._pending_restore_confirmation.discard(info_hash)
            return
        record = self._records.get(info_hash)
        if record is not None:
            if record.completed_at is None:
                record.completed_at = time.time()
            if self._settings.provenance_manifest_enabled:
                _write_provenance_manifest(record)
        self.torrent_finished.emit(info_hash)

    def _on_torrent_checked(self, info_hash: str) -> None:
        # libtorrent posts torrent_finished_alert *before* torrent_checked_alert
        # when the check finds the data complete. A check that ends without
        # it found pieces missing: the finish once they are downloaded again
        # is a real one (toast, webhook, Defender scan...).
        self._pending_restore_confirmation.discard(info_hash)
        if info_hash in self._resume_after_check:
            self._resume_after_check.discard(info_hash)
            self.resume_torrent(info_hash)  # still refused under CCCP if data is missing

    def _on_tracker_error(self, info_hash: str, message: str) -> None:
        self.tracker_error.emit(info_hash, message)

    def _on_save_resume_data(self, info_hash: str, params) -> None:
        persistence.save_resume_params(info_hash, params)

    def _on_torrent_removed(self, info_hash: str) -> None:
        self._records.pop(info_hash, None)
        self._handles.pop(info_hash, None)
        self._speed_history.pop(info_hash, None)
        getattr(self, "_file_entries_cache", {}).pop(info_hash, None)
        self._pending_restore_confirmation.discard(info_hash)
        self._resume_after_check.discard(info_hash)
        self._categories.remove(info_hash)
        if info_hash in self._awaiting_analysis:
            self._awaiting_analysis.discard(info_hash)
            self._save_awaiting_analysis()
        if info_hash in self._start_once_analysed:
            self._start_once_analysed.discard(info_hash)
            self._save_start_once_analysed()
        if self._matched_rules.pop(info_hash, None) is not None:
            persistence.save_json(get_matched_rules_path(), self._matched_rules)
        persistence.delete_resume_file(info_hash)
        self.torrent_removed.emit(info_hash)

    def _on_torrent_added(self, info_hash: str, handle, error: str) -> None:
        # add_torrent_from_* already did their bookkeeping synchronously; only
        # the async adds queued by _restore_previous_session land here.
        if info_hash not in self._pending_restore:
            return
        self._pending_restore.discard(info_hash)
        if not error:
            self._handles[info_hash] = handle
            record = self._records.get(info_hash)
            if record is not None and record.awaiting_analysis and not record.is_magnet_awaiting_metadata:
                # Its metadata came in at the quit, too late for whoever
                # analyses it (e.g. RSS), and libtorrent won't announce it again.
                self._on_metadata_received(info_hash)
            return
        logger.error("Failed to restore torrent %s from saved resume data: %s", info_hash, error)
        self._pending_restore_confirmation.discard(info_hash)
        if info_hash in self._handles:
            return  # added again by hand meanwhile: that record is live, keep it
        # Not torrent_removed: the user didn't remove it, so its .fastresume,
        # tags and share limit stay for next launch -- only the row goes.
        self._records.pop(info_hash, None)
        self.torrent_restore_failed.emit(info_hash)

    def _on_storage_moved(self, info_hash: str, new_path: str) -> None:
        record = self._records.get(info_hash)
        if record is not None:
            record.save_path = new_path
        if info_hash in self._quiet_moves:
            self._quiet_moves.discard(info_hash)
            return
        self.storage_moved.emit(info_hash, new_path)

    def _on_storage_move_failed(self, info_hash: str, message: str) -> None:
        logger.warning("Moving torrent %s failed: %s", info_hash, message)
        self.storage_move_failed.emit(info_hash, message)

    def _on_file_error(self, info_hash: str, message: str) -> None:
        # self.pause_torrent, not a raw handle.pause() -- it also clears
        # auto_managed, without which libtorrent's queue manager would just
        # un-pause this torrent again on its own within a couple of ticks.
        self.pause_torrent(info_hash)
        self.file_error.emit(info_hash, message)

    # ------------------------------------------------------------------- API

    def add_torrent_from_file(
        self, path: str, save_path: str | None = None, excluded_indices: set[int] | None = None
    ) -> str:
        save_path = save_path or str(get_default_download_dir())
        atp = add_params.from_torrent_file(
            path, save_path, excluded_indices, restrict_discovery=self._settings.restrict_discovery
        )
        blocked = _is_download_start_blocked(self._settings.theme, progress=0.0)
        if blocked:
            # Unlike a magnet (held in upload mode pending analysis), a
            # .torrent file normally starts downloading immediately -- hold
            # it paused instead so "no downloading under CCCP" is actually
            # enforced here too, not just at start_after_analysis/resume.
            atp.flags &= ~lt.torrent_flags.auto_managed
            atp.flags |= lt.torrent_flags.paused
        info_hash = self._add(atp, awaiting_analysis=False)
        if blocked:
            # Its data may already be on disk (the Share page, a re-add): a
            # share then, which CCCP allows. Only its check tells; refused
            # once checked if pieces are missing.
            self._resume_once_checked(self._handles[info_hash], info_hash)
        return info_hash

    def add_torrent_from_magnet(self, uri: str, save_path: str | None = None) -> str:
        save_path = save_path or str(get_default_download_dir())
        atp = add_params.from_magnet_uri(uri, save_path, restrict_discovery=self._settings.restrict_discovery)
        # Running, or it would contact no peer and its metadata would never
        # arrive, but in upload mode: no piece is downloaded until
        # start_after_analysis, once the file list has been analysed (see
        # metadata_received). Not auto-managed, or libtorrent would leave upload
        # mode by itself after optimistic_disk_retry.
        atp.flags &= ~(lt.torrent_flags.auto_managed | lt.torrent_flags.paused)
        atp.flags |= lt.torrent_flags.upload_mode
        info_hash = self._add(atp, awaiting_analysis=True)
        self._awaiting_analysis.add(info_hash)
        if not self._awaiting_save_queued:
            self._awaiting_save_queued = True
            QTimer.singleShot(0, self, lambda: self._awaiting_save_queued and self._save_awaiting_analysis())
        return info_hash

    def _save_awaiting_analysis(self) -> None:
        self._awaiting_save_queued = False
        persistence.save_json(get_awaiting_analysis_path(), sorted(self._awaiting_analysis))

    def _save_start_once_analysed(self) -> None:
        persistence.save_json(get_magnets_to_start_path(), sorted(self._start_once_analysed))

    def start_awaiting_magnet(self, info_hash: str) -> bool:
        """The user starts, from the Downloads page, a magnet nobody will
        analyse any more (left awaiting by a restart, or by another magnet
        analysed on the Add page): what RSS and remote add do -- danger scan
        with the auto-exclude threshold, then start_after_analysis -- now if
        its metadata is in, else as soon as it arrives (saved for a restart).
        True when it waits for its metadata."""
        record = self._records.get(info_hash)
        if record is not None and _is_download_start_blocked(self._settings.theme, record.progress):
            self.download_blocked_by_theme.emit(info_hash)
            return False
        if self.get_torrent_files(info_hash):
            self._scan_and_start(info_hash)
            return False
        self._start_once_analysed.add(info_hash)
        self._save_start_once_analysed()
        self.resume_torrent(info_hash)  # a paused magnet would never fetch its metadata
        return True

    def _scan_and_start(self, info_hash: str) -> None:
        from torrent2000.danger_scanner.scanner import auto_exclude_indices, scan_files

        try:
            files = self.get_torrent_files(info_hash)
            excluded = auto_exclude_indices(scan_files(files), self._settings.danger_auto_exclude_threshold)
            if excluded:
                self.exclude_files(info_hash, excluded)
        except Exception:
            logger.exception("Failed to scan magnet torrent %s for dangerous files", info_hash)
        self.start_after_analysis(info_hash)

    def _add(self, atp: "lt.add_torrent_params", awaiting_analysis: bool) -> str:
        info_hash = add_params.info_hash_hex(atp)
        if info_hash in self._records:
            # libtorrent hands a magnet the live handle back (and refuses a
            # file): a new record must not replace the live one's category,
            # pin, rule and state.
            raise TorrentAlreadyPresentError(info_hash)
        handle = self._session.add_torrent(atp)
        if not awaiting_analysis and info_hash in self._awaiting_analysis:
            # Left by a magnet of it lost in a crash before its first resume
            # save: the restore would hold this one in upload mode.
            self._awaiting_analysis.discard(info_hash)
            self._save_awaiting_analysis()
        self._records[info_hash] = TorrentRecord(
            info_hash=info_hash,
            name=_atp_name(atp),
            save_path=atp.save_path,
            awaiting_analysis=awaiting_analysis,
            is_magnet_awaiting_metadata=atp.ti is None,
        )
        self._handles[info_hash] = handle
        if self._settings.lan_peer_cache_enabled:
            # If this exact torrent was already seen on this LAN before,
            # try reconnecting those remembered local peers right away --
            # see engine/lan_peer_cache.py.
            reconnect_cached_peers(handle, self._lan_peer_cache_store, info_hash)
        self.torrent_added.emit(info_hash)
        return info_hash

    def get_record(self, info_hash: str) -> TorrentRecord | None:
        return self._records.get(info_hash)

    def all_records(self) -> list[TorrentRecord]:
        return list(self._records.values())

    def set_torrent_category(self, info_hash: str, category: str) -> None:
        record = self._records.get(info_hash)
        if record is not None:
            record.category = category
        self._categories.set(info_hash, category)

    def list_categories(self) -> list[str]:
        """Distinct non-empty categories currently used by at least one
        known torrent, sorted -- not just everything ever persisted (a
        category last used by a since-removed torrent shouldn't linger in
        e.g. a filter dropdown)."""
        used = {record.category for record in self._records.values() if record.category}
        return sorted(used)

    def get_speed_history(self, info_hash: str) -> list[tuple[int, int]]:
        """Oldest -> newest (download_rate, upload_rate) samples collected
        since the torrent was added (or since this process started, for a
        torrent restored from a previous session)."""
        return list(self._speed_history.get(info_hash, []))

    def get_torrent_files(self, info_hash: str):
        from torrent2000.engine.torrent_files import files_from_torrent_info

        handle = self._handles.get(info_hash)
        if handle is None:
            return []
        ti = handle.torrent_file()
        if ti is None:
            return []
        return files_from_torrent_info(ti)

    def get_piece_availability(self, info_hash: str) -> dict:
        """Per-piece download/rarity snapshot for one torrent, for the piece
        availability map dialog. Empty/safe result (matching
        get_torrent_files) if the handle is missing/invalid or metadata
        hasn't arrived yet -- torrent_file() is None until then, e.g. a
        magnet still resolving."""
        handle = self._handles.get(info_hash)
        if handle is None or not handle.is_valid():
            return {"num_pieces": 0, "have": [], "availability": []}
        ti = handle.torrent_file()
        if ti is None:
            return {"num_pieces": 0, "have": [], "availability": []}
        return {
            "num_pieces": ti.num_pieces(),
            # query_pieces only: the default flags also compute every other
            # optional status field, none of which this 2 s poll uses.
            "have": list(handle.status(lt.torrent_handle.query_pieces).pieces),
            "availability": list(handle.piece_availability()),
        }

    def get_file_progress(self, info_hash: str) -> list[dict]:
        """Per-file size/bytes-downloaded breakdown, for the storage
        sunburst dialog -- same empty-list-on-not-ready contract as
        get_torrent_files() (handle missing/invalid, or metadata not
        received yet)."""
        downloaded = self.get_file_downloaded(info_hash)
        if not downloaded:
            return []
        return [
            {"index": e.index, "path": e.path, "size": e.size, "downloaded": d}
            for e, d in zip(self._file_entries_cache[info_hash], downloaded)
        ]

    def get_file_downloaded(self, info_hash: str) -> list[int]:
        """Just the bytes-downloaded column of get_file_progress(), in the
        same order -- the only part of it that changes between two polls of
        the sunburst dialog. The file list itself (paths, sizes) is immutable
        once metadata is in, so it's built once per torrent and cached
        (purged in _on_torrent_removed), never while metadata is missing."""
        from torrent2000.engine.torrent_files import files_from_torrent_info

        handle = self._handles.get(info_hash)
        if handle is None or not handle.is_valid():
            return []
        # Lazily created: several tests build SessionManager via __new__.
        cache = getattr(self, "_file_entries_cache", None)
        if cache is None:
            cache = self._file_entries_cache = {}
        entries = cache.get(info_hash)
        if entries is None:
            ti = handle.torrent_file()
            if ti is None:
                return []
            entries = cache[info_hash] = files_from_torrent_info(ti)
        progress = handle.file_progress()
        return [progress[e.index] for e in entries]

    def get_allocated_size(self, info_hash: str) -> int:
        """Real on-disk allocated bytes for this torrent's files, as opposed
        to record.total_size (the logical/apparent size) -- can differ on a
        compressed or sparse NTFS volume, or if the disk couldn't fully
        allocate a file the app otherwise reports as complete."""
        from torrent2000.engine.disk_allocation import compressed_file_size
        from torrent2000.engine.torrent_files import files_from_torrent_info

        handle = self._handles.get(info_hash)
        record = self._records.get(info_hash)
        if handle is None or record is None:
            return 0
        ti = handle.torrent_file()
        if ti is None:
            return 0
        save_path = Path(record.save_path)
        try:
            resolved_root = save_path.resolve()
        except (OSError, ValueError):
            return 0
        total = 0
        for entry in files_from_torrent_info(ti):
            file_path = save_path / entry.path
            if _is_confined(file_path, resolved_root):
                total += compressed_file_size(file_path)
        return total

    def lock_torrent(self, info_hash: str) -> None:
        """Archive mode: mark this torrent's real files read-only on disk
        (os.chmod), so a finished download can't be edited/moved/corrupted
        by mistake. Best-effort per file -- see _chmod_torrent_files."""
        self._chmod_torrent_files(info_hash, read_only=True)
        record = self._records.get(info_hash)
        if record is not None:
            record.locked = True

    def unlock_torrent(self, info_hash: str) -> None:
        self._chmod_torrent_files(info_hash, read_only=False)
        record = self._records.get(info_hash)
        if record is not None:
            record.locked = False

    def set_matched_rule_name(self, info_hash: str, rule_name: str | None) -> None:
        """Records which routing_rules.RoutingRule (if any) picked this
        torrent's destination -- see TorrentRecord.matched_rule_name and
        engine/post_complete_action_service.py, which looks this back up
        once the torrent finishes. Only called by the fully-automatic add
        paths (watch folder, RSS) where the rule's destination is used
        verbatim; the manual Add page lets the user freely edit the
        suggested destination, so there's no reliable "the rule is what
        actually applied" signal to record there."""
        record = self._records.get(info_hash)
        if record is not None:
            record.matched_rule_name = rule_name
            if rule_name:
                self._matched_rules[info_hash] = rule_name
            else:
                self._matched_rules.pop(info_hash, None)
            persistence.save_json(get_matched_rules_path(), self._matched_rules)

    def pin_torrent(self, info_hash: str) -> None:
        """Pin panel: no disk/engine effect, just an in-memory flag the UI
        uses to keep this torrent at the top of the list."""
        record = self._records.get(info_hash)
        if record is not None:
            record.pinned = True

    def unpin_torrent(self, info_hash: str) -> None:
        record = self._records.get(info_hash)
        if record is not None:
            record.pinned = False

    def set_deadline(self, info_hash: str, timestamp: float | None) -> None:
        """Set (or clear, with None) the target completion time used by
        _apply_deadline_priorities. No immediate queue move here -- the next
        tick's sweep picks it up within _DEADLINE_SWEEP_INTERVAL_S."""
        record = self._records.get(info_hash)
        if record is not None:
            record.deadline = timestamp

    def _chmod_torrent_files(self, info_hash: str, read_only: bool) -> None:
        record = self._records.get(info_hash)
        if record is None:
            return
        save_path = Path(record.save_path)
        try:
            resolved_root = save_path.resolve()
        except (OSError, ValueError):
            logger.warning("lock_torrent: invalid save_path %r, nothing chmod-ed (info_hash=%s)", save_path, info_hash)
            return
        for entry in self.get_torrent_files(info_hash):
            file_path = save_path / entry.path
            if not _is_confined(file_path, resolved_root):
                logger.warning(
                    "lock_torrent: refusing to chmod %s -- outside save_path (info_hash=%s)", file_path, info_hash
                )
                continue
            try:
                mode = file_path.stat().st_mode
                new_mode = mode & ~stat.S_IWUSR if read_only else mode | stat.S_IWUSR
                os.chmod(file_path, new_mode)
            except OSError:
                # A file missing on disk, a drive disconnected mid-seed, a
                # permission we don't own -- this is a best-effort archive
                # lock, not a transactional guarantee. Skip it and keep
                # going rather than aborting the rest of the torrent's files.
                logger.warning(
                    "lock_torrent: could not chmod %s (info_hash=%s, read_only=%s)",
                    file_path,
                    info_hash,
                    read_only,
                )

    def exclude_files(self, info_hash: str, excluded_indices: set[int]) -> None:
        """Set priority 0 (excluded/"cleaned") for the given file indices,
        leaving every other file's existing priority untouched. Indices are
        the same ones reported by files_from_torrent_info (pad files already
        filtered out, so this is safe to call with UI-selected indices)."""
        handle = self._handles.get(info_hash)
        if handle is None:
            return
        priorities = handle.get_file_priorities()
        for idx in excluded_indices:
            if 0 <= idx < len(priorities):
                priorities[idx] = FILE_PRIORITY_EXCLUDED
        handle.prioritize_files(priorities)

    def get_file_priorities(self, info_hash: str) -> list[int]:
        """libtorrent's per-file priorities, indexed like get_torrent_files'
        entries; [] if there's no handle."""
        handle = self._handles.get(info_hash)
        if handle is None:
            return []
        return list(handle.get_file_priorities())

    def set_file_priorities(self, info_hash: str, excluded_indices: set[int]) -> None:
        """Full replacement, unlike exclude_files: every file's priority is
        set explicitly (excluded or default), so a file previously excluded
        but no longer in excluded_indices is restored to normal priority.
        Needed for a post-add file editor where the user can both check and
        uncheck files, as opposed to exclude_files' one-way "clean" action."""
        handle = self._handles.get(info_hash)
        if handle is None:
            return
        priorities = handle.get_file_priorities()
        for idx in range(len(priorities)):
            priorities[idx] = FILE_PRIORITY_EXCLUDED if idx in excluded_indices else FILE_PRIORITY_DEFAULT
        handle.prioritize_files(priorities)

    def start_after_analysis(self, info_hash: str) -> None:
        handle = self._handles.get(info_hash)
        record = self._records.get(info_hash)
        if handle is None or record is None:
            return
        if _is_download_start_blocked(self._settings.theme, record.progress):
            self.download_blocked_by_theme.emit(info_hash)
            return
        record.awaiting_analysis = False
        if info_hash in self._awaiting_analysis:
            self._awaiting_analysis.discard(info_hash)
            self._save_awaiting_analysis()
        handle.unset_flags(lt.torrent_flags.upload_mode)
        handle.set_flags(lt.torrent_flags.auto_managed)
        handle.resume()
        # awaiting_analysis.json just changed: a .fastresume left until the
        # periodic save would still hold it (and any pause from while it
        # was held) after a crash -- see _restore_previous_session.
        handle.save_resume_data(lt.torrent_handle.save_info_dict)

    def pause_torrent(self, info_hash: str) -> None:
        handle = self._handles.get(info_hash)
        # A ghost record (stale/invalid handle still sitting in _records
        # between removal and the torrent_removed_alert that clears it) makes
        # any real handle call raise RuntimeError("invalid torrent handle
        # used") -- checked here rather than only at each caller so every
        # pause path (manual pause, share-limit enforcement, battery pause,
        # remote API, theme enforcement) is covered by one guard.
        if handle is None or not handle.is_valid():
            return
        self._resume_after_check.discard(info_hash)  # paused again: no resume once checked
        # A torrent left auto-managed gets silently un-paused again by
        # libtorrent's own queue manager within a couple of ticks (it decides
        # pause/resume for auto-managed torrents itself based on the active
        # download/seed limits) -- clearing the flag first is required for a
        # manual pause to actually stick.
        handle.unset_flags(lt.torrent_flags.auto_managed)
        handle.pause()

    def resume_torrent(self, info_hash: str) -> None:
        handle = self._handles.get(info_hash)
        record = self._records.get(info_hash)
        if handle is None or not handle.is_valid():
            return
        if record is not None and _is_download_start_blocked(self._settings.theme, record.progress):
            status = handle.status()  # during or just after a check, the record lags behind
            # Not a magnet held for its analysis: auto-managed, it would leave upload mode.
            if status.state in _CHECKING_STATES and not record.awaiting_analysis:
                self._resume_once_checked(handle, info_hash)
                return
            if _is_download_start_blocked(self._settings.theme, status.progress):
                self.download_blocked_by_theme.emit(info_hash)
                return
        # Resumed by hand while recheck_torrent checks it: no pause once checked.
        handle.unset_flags(lt.torrent_flags.stop_when_ready)
        # A magnet awaiting analysis only goes back to fetching its metadata,
        # in upload mode: auto-management would end that mode by itself.
        if record is None or not record.awaiting_analysis:
            handle.set_flags(lt.torrent_flags.auto_managed)
        handle.resume()

    def enforce_theme_download_policy(self) -> None:
        """Call after the active theme changes. CCCP's "no downloading,
        only sharing" rule pauses every torrent still short of 100% the
        moment it's switched on; switching away doesn't auto-resume them,
        matching how pause/resume already require an explicit user action
        everywhere else in the app."""
        if self._settings.theme != CCCP_THEME_ID:
            return
        paused_count = 0
        for info_hash, record in list(self._records.items()):
            if record.awaiting_analysis or record.progress >= 1.0 or record.state == TorrentState.PAUSED:
                continue
            handle = self._handles.get(info_hash)
            if handle is not None and handle.is_valid() and handle.status().state in _CHECKING_STATES:
                self._resume_once_checked(handle, info_hash)  # its progress is the check's, not missing data
                continue
            self.pause_torrent(info_hash)
            paused_count += 1
        if paused_count:
            self.theme_downloads_paused.emit(paused_count)

    def _resume_once_checked(self, handle, info_hash: str) -> None:
        """CCCP refuses a download, but a torrent being checked may well be a
        complete seed: only its check can tell. Checked now, paused again once
        checked (stop_when_ready, as in recheck_torrent) before any piece is
        requested, then resumed by _on_torrent_checked if nothing is missing."""
        handle.set_flags(lt.torrent_flags.auto_managed | lt.torrent_flags.stop_when_ready)
        handle.resume()
        self._resume_after_check.add(info_hash)

    def set_sequential_download(self, info_hash: str, enabled: bool) -> None:
        """Catalogue idea "telechargement sequentiel -> vrai mode streaming":
        beyond the existing handle.set_sequential_download() alone (which
        only orders piece REQUESTS, no urgency signal), also apply
        deadline-based piece priorities via handle.set_piece_deadline() --
        libtorrent's own streaming-oriented API (used by real media-player
        integrations) -- to the head of the torrent's largest file, so the
        pieces a player would need first actually download with real
        urgency instead of merely "before pieces further along"."""
        handle = self._handles.get(info_hash)
        if handle is None:
            return
        handle.set_sequential_download(enabled)
        if enabled:
            self._apply_streaming_deadlines(handle)
        else:
            handle.clear_piece_deadlines()
            self._restore_file_piece_priorities(handle)

    def _restore_file_piece_priorities(self, handle) -> None:
        """clear_piece_deadlines() leaves every deadline piece at priority 1
        whatever its file's priority (an excluded file's head keeps
        downloading, a wanted file's head is demoted), so re-derive each
        piece's priority from its files the way libtorrent does: the highest
        overlapping file wins, pad and empty files don't count."""
        ti = handle.torrent_file()
        if ti is None:
            return
        fs = ti.files()
        piece_length = ti.piece_length()
        if piece_length <= 0:
            return
        piece_priorities = [0] * ti.num_pieces()
        for index, priority in enumerate(handle.get_file_priorities()):
            size = fs.file_size(index)
            if priority == 0 or size == 0 or fs.file_flags(index) & lt.file_storage.flag_pad_file:
                continue
            offset = fs.file_offset(index)
            for piece in range(offset // piece_length, (offset + size - 1) // piece_length + 1):
                piece_priorities[piece] = max(piece_priorities[piece], priority)
        handle.prioritize_pieces(piece_priorities)

    def _apply_streaming_deadlines(self, handle) -> None:
        ti = handle.torrent_file()
        if ti is None:
            return  # metadata not ready yet (magnet still resolving) -- nothing to prioritize
        fs = ti.files()
        if fs.num_files() == 0:
            return
        piece_length = ti.piece_length()
        if piece_length <= 0:
            return
        # set_piece_deadline() downloads a piece even at priority 0, so only a
        # file the user actually wants can be the one streamed.
        file_priorities = handle.get_file_priorities()
        wanted = [index for index in range(fs.num_files()) if file_priorities[index] > 0]
        if not wanted:
            return
        largest_index = max(wanted, key=fs.file_size)
        offset = fs.file_offset(largest_index)
        size = fs.file_size(largest_index)
        first_piece = offset // piece_length
        last_piece = min(ti.num_pieces() - 1, (offset + max(size, 1) - 1) // piece_length)
        last_head_piece = min(last_piece, first_piece + _STREAMING_HEAD_PIECE_COUNT - 1)
        for rank, piece in enumerate(range(first_piece, last_head_piece + 1)):
            handle.set_piece_deadline(piece, rank * _STREAMING_DEADLINE_STEP_MS)

    def move_queue_up(self, info_hash: str) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            handle.queue_position_up()

    def move_queue_down(self, info_hash: str) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            handle.queue_position_down()

    def remove_torrent(self, info_hash: str, delete_files: bool = False) -> None:
        handle = self._handles.get(info_hash)
        if handle is None:
            return
        flags = lt.session.delete_files if delete_files else 0
        self._session.remove_torrent(handle, flags)

    def get_trackers(self, info_hash: str) -> list[TrackerInfo]:
        handle = self._handles.get(info_hash)
        if handle is None:
            return []
        return tracker_ops.get_trackers(handle)

    def get_peer_info(self, info_hash: str) -> list[PeerInfo]:
        handle = self._handles.get(info_hash)
        if handle is None or not handle.is_valid():
            return []
        raw_peers = handle.get_peer_info()
        if self._settings.peer_reputation_enabled:
            # See engine/peer_reputation.py: this is the one chokepoint all
            # peer_info flows through, so reputation observation piggybacks
            # here instead of running its own background poll.
            self._peer_reputation_tracker.observe(info_hash, raw_peers)
        if self._settings.lan_peer_cache_enabled:
            # See engine/lan_peer_cache.py: same chokepoint/reasoning as
            # peer reputation above -- only RFC1918 IPs actually get kept.
            self._lan_peer_cache_store.record_peers(info_hash, raw_peers)
        # lt.peer_info.ip is a (address, port) tuple in this build (2.0.13.0)
        # -- verified via help(lt.peer_info)/get_peer_info.
        return [
            PeerInfo(
                ip=f"{p.ip[0]}:{p.ip[1]}",
                client=p.client,
                progress=p.progress,
                down_speed=p.payload_down_speed,
                up_speed=p.payload_up_speed,
            )
            for p in raw_peers
        ]

    def _flush_peer_stores(self) -> None:
        self._peer_reputation_store.flush()
        self._lan_peer_cache_store.flush()

    def get_peer_reputation_score(self, display_ip: str) -> str:
        """"good" | "neutral" | "bad" for a peer IP as shown in the UI
        (PeerInfo.ip, "address:port"). Always "neutral" while
        Settings.peer_reputation_enabled is off, since nothing is being
        journaled in that case."""
        if not self._settings.peer_reputation_enabled:
            return "neutral"
        record = self._peer_reputation_store.get(ip_from_display(display_ip))
        return score_label(record)

    def get_magnet_uri(self, info_hash: str) -> str | None:
        handle = self._handles.get(info_hash)
        if handle is None or not handle.is_valid():
            return None
        try:
            return lt.make_magnet_uri(handle)
        except Exception:
            logger.exception("Failed to build magnet URI for %s", info_hash)
            return None

    def add_tracker(self, info_hash: str, url: str, tier: int = 0) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            tracker_ops.add_tracker(handle, url, tier)

    def remove_tracker(self, info_hash: str, url: str) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            tracker_ops.remove_tracker(handle, url)

    def set_restrict_discovery(self, enabled: bool) -> None:
        """Live-apply the DHT/LSD discovery restriction (see
        _build_session_settings) without requiring a session restart, so a
        change on the Settings screen takes effect immediately."""
        self._session.apply_settings(
            {
                "enable_dht": not enabled,
                "enable_lsd": not enabled,
            }
        )

    def recheck_torrent(self, info_hash: str) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            # Whatever its progress -- 0 for a complete torrent restored while
            # its drive was unplugged: data the check itself finds complete
            # is no download. Pieces it finds missing drop the mark
            # (_on_torrent_checked), so the finish once they're downloaded is.
            self.expect_existing_data(info_hash)
            flags = handle.flags()
            handle.force_recheck()
            if flags & lt.torrent_flags.paused and not flags & (
                lt.torrent_flags.auto_managed | lt.torrent_flags.upload_mode
            ):
                # Paused by the user: libtorrent leaves its check at 0 % until
                # a resume, which CCCP refuses at 0 % and which, after a
                # restart, reported a new finish. Checked now, in the checking
                # queue, then paused again by libtorrent before any peer or
                # tracker is contacted (set after force_recheck: set on a
                # seed, stop_when_ready fires at once). Not a magnet held for
                # its analysis: auto-managed, it would leave upload mode.
                handle.set_flags(lt.torrent_flags.auto_managed | lt.torrent_flags.stop_when_ready)

    def expect_existing_data(self, info_hash: str) -> None:
        """The torrent's data should already be complete on disk (a recheck,
        a share): libtorrent fires torrent_finished_alert once its check
        confirms it, and that is no download to report -- no toast, webhook,
        post-complete action or shutdown countdown. A check that finds data
        missing drops the mark (_on_torrent_checked)."""
        self._pending_restore_confirmation.add(info_hash)

    def move_storage(self, info_hash: str, new_path: str, quiet: bool = False) -> None:
        """quiet: no storage_moved (the "move finished" toast) for this one,
        e.g. a just-added magnet placed in the folder chosen on the Add page."""
        if not is_safe_move_destination(new_path):
            logger.warning("Refusing to move torrent %s to disallowed destination: %r", info_hash, new_path)
            self.move_storage_refused.emit(info_hash, new_path)  # callers are fire-and-forget
            return
        handle = self._handles.get(info_hash)
        if handle is not None:
            if quiet:
                self._quiet_moves.add(info_hash)
            else:
                self._quiet_moves.discard(info_hash)
            handle.move_storage(new_path)

    def set_proxy(self, settings: Settings) -> None:
        self._session.apply_settings(proxy.build_settings_fragment(settings.proxy))

    def set_encryption_mode(self, mode: str) -> None:
        """Live-apply the protocol-encryption policy (see
        _build_session_settings/_encryption_settings_fragment) without
        requiring a session restart."""
        self._session.apply_settings(_encryption_settings_fragment(mode))

    def set_network_interface(self, interface_name: str) -> None:
        fragment = proxy.build_interface_fragment(interface_name)
        if fragment:
            self._session.apply_settings(fragment)

    def set_rate_limits(self, download_kbps: int, upload_kbps: int) -> None:
        self._session.apply_settings(
            {
                "download_rate_limit": download_kbps * 1024,
                "upload_rate_limit": upload_kbps * 1024,
            }
        )

    def set_max_active_downloads(self, count: int) -> None:
        self._session.apply_settings(
            {
                "active_downloads": count,
                "active_seeds": count,
                "active_checking": count,
                "active_limit": count * 2,
            }
        )

    # -------------------------------------------------------------- lifecycle

    def _restore_previous_session(self) -> None:
        # async_add_torrent, not add_torrent: the synchronous call blocks this
        # (GUI) thread until libtorrent's network thread services it, and that
        # thread first runs its whole startup against the OS network stack --
        # unbounded when that stack stalls (see tests/conftest.py). Each handle
        # is bound, or the record dropped, when its add_torrent_alert reaches
        # _on_torrent_added (see _bind_restored_handles).
        atps = persistence.load_all_resume_params()
        # Nothing pops the alert queue before the event loop runs, and past
        # alert_queue_size libtorrent drops alerts: at the default 2000, the
        # add_torrent_alerts of a restore beyond ~3,600 torrents, leaving
        # those records without a handle for the whole session. Room for 4
        # alerts per torrent keeps them all, each torrent_finished included
        # (6,500 complete torrents: nothing dropped). apply_settings() is
        # queued to the network thread ahead of the adds, so it covers them.
        queue_size = max(self._alert_queue_floor, 4 * len(atps))
        self._session.apply_settings({"alert_queue_size": queue_size})
        for atp in atps:
            # One corrupt/stale resume entry must not take down startup for
            # every other torrent. Most bad data never gets here (refused by
            # read_resume_data, see load_all_resume_params); some raises here
            # (e.g. an empty save_path); the add_torrent_alert reports the rest.
            try:
                info_hash = add_params.info_hash_hex(atp)
                # awaiting_analysis.json is written at once, the .fastresume
                # only every so often: after an abnormal exit they can
                # disagree, and the awaiting set wins (see
                # add_torrent_from_magnet and start_after_analysis).
                if info_hash in self._awaiting_analysis:
                    if not atp.flags & lt.torrent_flags.upload_mode:
                        atp.flags &= ~lt.torrent_flags.paused  # saved started: no pause of the user's
                    atp.flags |= lt.torrent_flags.upload_mode
                    atp.flags &= ~lt.torrent_flags.auto_managed
                elif atp.flags & lt.torrent_flags.upload_mode:
                    # Kept paused if it was: libtorrent also enters upload
                    # mode on a full disk, and _on_file_error pauses it.
                    atp.flags &= ~lt.torrent_flags.upload_mode
                    if not atp.flags & lt.torrent_flags.paused:
                        atp.flags |= lt.torrent_flags.auto_managed
                self._session.async_add_torrent(atp)
            except Exception:
                logger.exception("Failed to restore a torrent from saved resume data")
                continue
            self._pending_restore.add(info_hash)
            record = TorrentRecord(
                info_hash=info_hash,
                name=_atp_name(atp),
                save_path=atp.save_path,
                all_time_downloaded=getattr(atp, "total_downloaded", 0),
                all_time_uploaded=getattr(atp, "total_uploaded", 0),
                category=self._categories.get(info_hash),
                awaiting_analysis=info_hash in self._awaiting_analysis,
                is_magnet_awaiting_metadata=atp.ti is None,
                matched_rule_name=self._matched_rules.get(info_hash),
            )
            self._records[info_hash] = record
            # Every one, not just those saved complete: a finish before its
            # check ends (_on_torrent_checked drops the mark) is data already
            # on disk -- e.g. a recheck interrupted by the quit before it began,
            # saved with no piece at all.
            self._pending_restore_confirmation.add(info_hash)
            self.torrent_added.emit(info_hash)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self._timer.stop()
        self._resume_save_timer.stop()
        if self._awaiting_save_queued:
            self._save_awaiting_analysis()
        # Tracked per torrent, not counted: up to _RESUME_SAVES_PER_TICK
        # periodic saves can still be in flight, and counting their alerts
        # could end the wait before some torrent's final save arrives. (A
        # periodic alert for the same torrent still clears it: libtorrent
        # answers in request order, so that state is at most one tick older.)
        pending: set = set()
        for handle in self._handles.values():
            if handle.is_valid():
                # save_info_dict is required for the saved .fastresume to
                # carry the torrent's actual metadata (atp.ti) -- without it,
                # _restore_previous_session() gets an atp with ti=None on the
                # next launch, and libtorrent silently re-fetches metadata
                # and re-hashes everything from scratch instead of doing a
                # real fast-resume, discarding all prior verified progress.
                handle.save_resume_data(lt.torrent_handle.save_info_dict)
                pending.add(handle)

        deadline = time.monotonic() + (timeout_ms / 1000)
        while pending and time.monotonic() < deadline:
            # Keeps Qt's event loop pumping window messages during this
            # blocking wait so Windows doesn't mark the process "Not
            # Responding" -- the wait/save logic itself is unchanged.
            QCoreApplication.processEvents()
            alerts = self._session.pop_alerts()
            for alert in alerts:
                if isinstance(alert, lt.save_resume_data_alert):
                    try:
                        info_hash = _hash_of(alert.handle)
                    except RuntimeError:
                        # Torrent removed while its periodic save was in
                        # flight: skip it like dispatch_all does, or the
                        # raise loses every save still to come.
                        pending.discard(alert.handle)
                        continue
                    persistence.save_resume_params(info_hash, alert.params)
                    pending.discard(alert.handle)
                elif isinstance(alert, (lt.save_resume_data_failed_alert,)):
                    pending.discard(alert.handle)
            time.sleep(0.05)


def _atp_name(atp: "lt.add_torrent_params") -> str:
    """A .torrent's name is in its ti, not in atp.name (a magnet's dn=):
    else a torrent finishing before its first status tick had no name in the
    "download finished" toast and webhook, and Defender scanned the whole
    download folder for it."""
    return atp.name or (atp.ti.name() if atp.ti is not None else "")


def _hash_hex(hashes) -> str:
    if hashes.has_v1():
        return str(hashes.v1)
    return str(hashes.v2)
