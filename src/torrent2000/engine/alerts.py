"""Turn popped libtorrent alerts into mutations on TorrentRecord + Qt signal emissions.

Kept separate from session_manager.py so the polling loop there isn't a
giant if/elif ladder.
"""

from typing import Callable

import libtorrent as lt

from torrent2000.engine.torrent_item import TorrentRecord, TorrentState


def status_to_record(status: "lt.torrent_status", record: TorrentRecord) -> None:
    record.name = status.name or record.name
    record.save_path = status.save_path
    record.total_size = status.total_wanted
    record.progress = status.progress
    record.download_rate = status.download_rate
    record.upload_rate = status.upload_rate
    record.num_peers = status.num_peers
    record.num_seeds = status.num_seeds
    record.total_downloaded = status.total_download
    record.total_uploaded = status.total_upload
    record.all_time_downloaded = status.all_time_download
    record.all_time_uploaded = status.all_time_upload
    record.error = status.error or ""
    record.current_tracker = status.current_tracker
    has_metadata = status.has_metadata
    record.is_magnet_awaiting_metadata = not has_metadata
    record.state = TorrentState.from_libtorrent_state(
        status.state, status.paused, has_metadata, record.awaiting_analysis
    )


class AlertDispatcher:
    """Dispatches popped alerts to callbacks. session_manager wires the callbacks
    to Qt signal emissions and record bookkeeping."""

    def __init__(
        self,
        on_state_update: Callable[[list], None],
        on_metadata_received: Callable[[str], None],
        on_torrent_finished: Callable[[str], None],
        on_tracker_error: Callable[[str, str], None],
        on_save_resume_data: Callable[[str, "lt.add_torrent_params"], None],
        on_torrent_removed: Callable[[str], None],
        on_torrent_added: Callable[["lt.torrent_handle"], None],
    ) -> None:
        self._on_state_update = on_state_update
        self._on_metadata_received = on_metadata_received
        self._on_torrent_finished = on_torrent_finished
        self._on_tracker_error = on_tracker_error
        self._on_save_resume_data = on_save_resume_data
        self._on_torrent_removed = on_torrent_removed
        self._on_torrent_added = on_torrent_added

    def dispatch_all(self, alerts: list) -> None:
        for alert in alerts:
            self.dispatch(alert)

    def dispatch(self, alert) -> None:
        if isinstance(alert, lt.state_update_alert):
            if alert.status:
                self._on_state_update(alert.status)
        elif isinstance(alert, lt.metadata_received_alert):
            self._on_metadata_received(_hash_of(alert.handle))
        elif isinstance(alert, lt.torrent_finished_alert):
            self._on_torrent_finished(_hash_of(alert.handle))
        elif isinstance(alert, lt.tracker_error_alert):
            self._on_tracker_error(_hash_of(alert.handle), alert.error_message or str(alert.message()))
        elif isinstance(alert, lt.save_resume_data_alert):
            self._on_save_resume_data(_hash_of(alert.handle), alert.params)
        elif isinstance(alert, lt.torrent_removed_alert):
            self._on_torrent_removed(_info_hash_hex(alert.info_hashes))
        elif isinstance(alert, lt.add_torrent_alert):
            if not alert.error:
                self._on_torrent_added(alert.handle)


def _hash_of(handle: "lt.torrent_handle") -> str:
    return _info_hash_hex(handle.status().info_hashes)


def _info_hash_hex(hashes) -> str:
    if hashes.has_v1():
        return str(hashes.v1)
    return str(hashes.v2)
