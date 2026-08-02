import logging

import libtorrent as lt
from PySide6.QtCore import QObject, QTimer, Signal

from torrent2000.config.paths import get_default_download_dir
from torrent2000.config.settings import Settings
from torrent2000.engine import add_params, persistence, proxy, trackers as tracker_ops
from torrent2000.engine.alerts import AlertDispatcher, status_to_record
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState, TrackerInfo
from torrent2000.theme_ids import CCCP_THEME_ID

logger = logging.getLogger(__name__)

FILE_PRIORITY_EXCLUDED = 0
FILE_PRIORITY_DEFAULT = 4

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
            "active_limit": settings.max_active_downloads * 2,
            "user_agent": "Torrent2000/0.1.0",
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

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._session = lt.session(_build_session_settings(settings))
        self._records: dict[str, TorrentRecord] = {}
        self._handles: dict[str, "lt.torrent_handle"] = {}

        self._dispatcher = AlertDispatcher(
            on_state_update=self._on_state_update,
            on_metadata_received=self._on_metadata_received,
            on_torrent_finished=self._on_torrent_finished,
            on_tracker_error=self._on_tracker_error,
            on_save_resume_data=self._on_save_resume_data,
            on_torrent_removed=self._on_torrent_removed,
            on_torrent_added=self._on_torrent_added,
        )

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(300)

        self._restore_previous_session()

    # ------------------------------------------------------------------ tick

    def _on_tick(self) -> None:
        self._session.post_torrent_updates()
        alerts = self._session.pop_alerts()
        if alerts:
            self._dispatcher.dispatch_all(alerts)

    # ------------------------------------------------------------- alert cbs

    def _on_state_update(self, status_list: list) -> None:
        for status in status_list:
            info_hash = _hash_hex(status.info_hashes)
            record = self._records.get(info_hash)
            if record is None:
                continue
            status_to_record(status, record)
            self.torrent_status_updated.emit(info_hash, record)

    def _on_metadata_received(self, info_hash: str) -> None:
        record = self._records.get(info_hash)
        if record is not None:
            record.is_magnet_awaiting_metadata = False
        self.metadata_received.emit(info_hash)

    def _on_torrent_finished(self, info_hash: str) -> None:
        self.torrent_finished.emit(info_hash)

    def _on_tracker_error(self, info_hash: str, message: str) -> None:
        self.tracker_error.emit(info_hash, message)

    def _on_save_resume_data(self, info_hash: str, params) -> None:
        persistence.save_resume_params(info_hash, params)

    def _on_torrent_removed(self, info_hash: str) -> None:
        self._records.pop(info_hash, None)
        self._handles.pop(info_hash, None)
        persistence.delete_resume_file(info_hash)
        self.torrent_removed.emit(info_hash)

    def _on_torrent_added(self, handle) -> None:
        pass  # bookkeeping already done synchronously in add_torrent_from_*

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
        self.torrent_added.emit(info_hash)
        return info_hash

    def get_record(self, info_hash: str) -> TorrentRecord | None:
        return self._records.get(info_hash)

    def all_records(self) -> list[TorrentRecord]:
        return list(self._records.values())

    def get_torrent_files(self, info_hash: str):
        from torrent2000.engine.torrent_files import files_from_torrent_info

        handle = self._handles.get(info_hash)
        if handle is None:
            return []
        ti = handle.torrent_file()
        if ti is None:
            return []
        return files_from_torrent_info(ti)

    def set_file_priorities(self, info_hash: str, priorities: list[int]) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            handle.prioritize_files(priorities)

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
        if handle is None:
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
        if handle is None:
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

    def get_queue_position(self, info_hash: str) -> int:
        handle = self._handles.get(info_hash)
        if handle is None:
            return -1
        return int(handle.queue_position())

    def move_queue_up(self, info_hash: str) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            handle.queue_position_up()

    def move_queue_down(self, info_hash: str) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            handle.queue_position_down()

    def move_queue_top(self, info_hash: str) -> None:
        handle = self._handles.get(info_hash)
        if handle is not None:
            handle.queue_position_top()

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
                "active_limit": count * 2,
            }
        )

    # -------------------------------------------------------------- lifecycle

    def _restore_previous_session(self) -> None:
        for atp in persistence.load_all_resume_params():
            try:
                info_hash = add_params.info_hash_hex(atp)
            except Exception:
                continue
            record = TorrentRecord(
                info_hash=info_hash,
                name=atp.name or "",
                save_path=atp.save_path,
                all_time_downloaded=getattr(atp, "total_downloaded", 0),
                all_time_uploaded=getattr(atp, "total_uploaded", 0),
            )
            self._records[info_hash] = record
            handle = self._session.add_torrent(atp)
            self._handles[info_hash] = handle
            self.torrent_added.emit(info_hash)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self._timer.stop()
        pending = 0
        for handle in self._handles.values():
            if handle.is_valid():
                handle.save_resume_data()
                pending += 1

        import time

        deadline = time.monotonic() + (timeout_ms / 1000)
        while pending > 0 and time.monotonic() < deadline:
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
