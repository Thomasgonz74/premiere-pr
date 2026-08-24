import collections
import json
import logging
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

import libtorrent as lt
from PySide6.QtCore import QCoreApplication, QObject, Signal

from torrent2000 import APP_VERSION
from torrent2000.config.paths import get_default_download_dir
from torrent2000.config.settings import Settings
from torrent2000.engine import add_params, persistence, proxy, trackers as tracker_ops
from torrent2000.engine.alerts import AlertDispatcher, status_to_record
from torrent2000.engine.lan_peer_cache import LanPeerCacheStore, reconnect_cached_peers
from torrent2000.engine.peer_reputation import PeerReputationStore, PeerReputationTracker, ip_from_display, score_label
from torrent2000.engine.torrent_categories import TorrentCategoryService
from torrent2000.engine.torrent_item import ACTIVE_DOWNLOAD_STATES, PeerInfo, TorrentRecord, TorrentState, TrackerInfo
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


class SessionManager(QObject):
    torrent_added = Signal(str)
    torrent_removed = Signal(str)
    torrent_status_updated = Signal(str, object)  # str info_hash, TorrentRecord
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
    # A disk/file I/O error (e.g. an external drive dropping out mid-write)
    # paused this torrent automatically. str info_hash, str error message.
    file_error = Signal(str, str)

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._session = lt.session(_build_session_settings(settings))
        self._records: dict[str, TorrentRecord] = {}
        self._handles: dict[str, "lt.torrent_handle"] = {}
        self._private_flag_checked: set[str] = set()
        # info_hashes restored from resume data that were *already* 100%
        # complete (all wanted pieces present) before this process started --
        # see _on_torrent_finished. libtorrent re-fires torrent_finished_alert
        # for these while verifying their fast-resume data on every restart,
        # even though nothing was actually (re)downloaded this session.
        self._pending_restore_confirmation: set[str] = set()
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
        # time.time() of the last deadline-priority sweep -- see
        # _apply_deadline_priorities, throttling that work inside _on_tick.
        self._last_deadline_sweep = 0.0

        self._dispatcher = AlertDispatcher(
            on_state_update=self._on_state_update,
            on_metadata_received=self._on_metadata_received,
            on_torrent_finished=self._on_torrent_finished,
            on_tracker_error=self._on_tracker_error,
            on_save_resume_data=self._on_save_resume_data,
            on_torrent_removed=self._on_torrent_removed,
            on_torrent_added=self._on_torrent_added,
            on_storage_moved=self._on_storage_moved,
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

    # ------------------------------------------------------------------ tick

    def _on_tick(self) -> None:
        self._session.post_torrent_updates()
        alerts = self._session.pop_alerts()
        if alerts:
            self._dispatcher.dispatch_all(alerts)
        self._apply_deadline_priorities()

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
            for _ in range(steps):
                self.move_queue_up(info_hash)

    def _save_all_resume_data(self) -> None:
        for handle in self._handles.values():
            if handle.is_valid():
                # only_if_modified skips torrents whose state hasn't changed
                # since their last save -- this timer fires every 2 minutes
                # for potentially many torrents, most of which are usually
                # idle between ticks.
                handle.save_resume_data(lt.torrent_handle.save_info_dict | lt.torrent_handle.only_if_modified)

    # ------------------------------------------------------------- alert cbs

    def _on_state_update(self, status_list: list) -> None:
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

    def _on_metadata_received(self, info_hash: str) -> None:
        record = self._records.get(info_hash)
        if record is not None:
            record.is_magnet_awaiting_metadata = False
        self.metadata_received.emit(info_hash)

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

    def _on_tracker_error(self, info_hash: str, message: str) -> None:
        self.tracker_error.emit(info_hash, message)

    def _on_save_resume_data(self, info_hash: str, params) -> None:
        persistence.save_resume_params(info_hash, params)

    def _on_torrent_removed(self, info_hash: str) -> None:
        self._records.pop(info_hash, None)
        self._handles.pop(info_hash, None)
        self._speed_history.pop(info_hash, None)
        self._pending_restore_confirmation.discard(info_hash)
        self._categories.remove(info_hash)
        persistence.delete_resume_file(info_hash)
        self.torrent_removed.emit(info_hash)

    def _on_torrent_added(self, handle) -> None:
        pass  # bookkeeping already done synchronously in add_torrent_from_*

    def _on_storage_moved(self, info_hash: str, new_path: str) -> None:
        record = self._records.get(info_hash)
        if record is not None:
            record.save_path = new_path
        self.storage_moved.emit(info_hash, new_path)

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
            # Unlike a magnet (always added paused pending analysis), a
            # .torrent file normally starts downloading immediately -- hold
            # it paused instead so "no downloading under CCCP" is actually
            # enforced here too, not just at start_after_analysis/resume.
            atp.flags &= ~lt.torrent_flags.auto_managed
            atp.flags |= lt.torrent_flags.paused
        info_hash = self._add(atp, awaiting_analysis=False)
        if blocked:
            self.download_blocked_by_theme.emit(info_hash)
        return info_hash

    def add_torrent_from_magnet(self, uri: str, save_path: str | None = None) -> str:
        save_path = save_path or str(get_default_download_dir())
        atp = add_params.from_magnet_uri(uri, save_path, restrict_discovery=self._settings.restrict_discovery)
        # Hold the torrent paused (and outside auto-management) until the
        # user has had a chance to analyze the file list once metadata
        # arrives -- see AddTorrentTab / metadata_received signal.
        atp.flags &= ~lt.torrent_flags.auto_managed
        atp.flags |= lt.torrent_flags.paused
        return self._add(atp, awaiting_analysis=True)

    def _add(self, atp: "lt.add_torrent_params", awaiting_analysis: bool) -> str:
        info_hash = add_params.info_hash_hex(atp)
        record = TorrentRecord(
            info_hash=info_hash,
            name=atp.name or "",
            save_path=atp.save_path,
            awaiting_analysis=awaiting_analysis,
            is_magnet_awaiting_metadata=atp.ti is None,
        )
        self._records[info_hash] = record
        handle = self._session.add_torrent(atp)
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
            "have": list(handle.status().pieces),
            "availability": list(handle.piece_availability()),
        }

    def get_file_progress(self, info_hash: str) -> list[dict]:
        """Per-file size/bytes-downloaded breakdown, for the storage
        sunburst dialog -- same empty-list-on-not-ready contract as
        get_torrent_files() (handle missing/invalid, or metadata not
        received yet)."""
        from torrent2000.engine.torrent_files import files_from_torrent_info

        handle = self._handles.get(info_hash)
        if handle is None or not handle.is_valid():
            return []
        ti = handle.torrent_file()
        if ti is None:
            return []
        downloaded = handle.file_progress()
        return [
            {"index": e.index, "path": e.path, "size": e.size, "downloaded": downloaded[e.index]}
            for e in files_from_torrent_info(ti)
        ]

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
        return sum(compressed_file_size(save_path / entry.path) for entry in files_from_torrent_info(ti))

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
        for entry in self.get_torrent_files(info_hash):
            file_path = save_path / entry.path
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
        handle.set_flags(lt.torrent_flags.auto_managed)
        handle.resume()

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
            self.download_blocked_by_theme.emit(info_hash)
            return
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
            self.pause_torrent(info_hash)
            paused_count += 1
        if paused_count:
            self.theme_downloads_paused.emit(paused_count)

    def set_sequential_download(self, info_hash: str, enabled: bool) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            handle.set_sequential_download(enabled)

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
        peers = []
        for p in raw_peers:
            # lt.peer_info.ip is a (address, port) tuple in this build
            # (2.0.13.0) -- verified via help(lt.peer_info)/get_peer_info.
            ip, port = p.ip
            peers.append(
                PeerInfo(
                    ip=f"{ip}:{port}",
                    client=p.client,
                    progress=p.progress,
                    down_speed=p.payload_down_speed,
                    up_speed=p.payload_up_speed,
                )
            )
        return peers

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
            handle.force_recheck()

    def move_storage(self, info_hash: str, new_path: str) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
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
        for atp in persistence.load_all_resume_params():
            # One corrupt/stale resume entry (e.g. its save_path no longer
            # exists) must not take down startup for every other torrent --
            # add_torrent(atp) itself needs covering here too, not just
            # info_hash_hex, since it's the call that can actually raise on
            # bad data.
            try:
                info_hash = add_params.info_hash_hex(atp)
                handle = self._session.add_torrent(atp)
            except Exception:
                logger.exception("Failed to restore a torrent from saved resume data")
                continue
            record = TorrentRecord(
                info_hash=info_hash,
                name=atp.name or "",
                save_path=atp.save_path,
                all_time_downloaded=getattr(atp, "total_downloaded", 0),
                all_time_uploaded=getattr(atp, "total_uploaded", 0),
                category=self._categories.get(info_hash),
            )
            self._records[info_hash] = record
            self._handles[info_hash] = handle
            if add_params.resume_data_is_complete(atp):
                self._pending_restore_confirmation.add(info_hash)
            self.torrent_added.emit(info_hash)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self._timer.stop()
        self._resume_save_timer.stop()
        pending = 0
        for handle in self._handles.values():
            if handle.is_valid():
                # save_info_dict is required for the saved .fastresume to
                # carry the torrent's actual metadata (atp.ti) -- without it,
                # _restore_previous_session() gets an atp with ti=None on the
                # next launch, and libtorrent silently re-fetches metadata
                # and re-hashes everything from scratch instead of doing a
                # real fast-resume, discarding all prior verified progress.
                handle.save_resume_data(lt.torrent_handle.save_info_dict)
                pending += 1

        import time

        deadline = time.monotonic() + (timeout_ms / 1000)
        while pending > 0 and time.monotonic() < deadline:
            # Keeps Qt's event loop pumping window messages during this
            # blocking wait so Windows doesn't mark the process "Not
            # Responding" -- the wait/save logic itself is unchanged.
            QCoreApplication.processEvents()
            alerts = self._session.pop_alerts()
            for alert in alerts:
                if isinstance(alert, lt.save_resume_data_alert):
                    info_hash = _hash_hex(alert.handle.status().info_hashes)
                    persistence.save_resume_params(info_hash, alert.params)
                    pending -= 1
                elif isinstance(alert, (lt.save_resume_data_failed_alert,)):
                    pending -= 1
            time.sleep(0.05)


def _hash_hex(hashes) -> str:
    if hashes.has_v1():
        return str(hashes.v1)
    return str(hashes.v2)
