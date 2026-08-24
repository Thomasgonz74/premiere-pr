"""Coverage for AlertDispatcher.dispatch()'s isinstance-based routing and
status_to_record()'s field-by-field copy onto TorrentRecord."""

from unittest.mock import MagicMock

import libtorrent as lt
import pytest

from torrent2000.engine.alerts import AlertDispatcher, status_to_record
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState


@pytest.fixture
def callbacks():
    return {
        "on_state_update": MagicMock(),
        "on_metadata_received": MagicMock(),
        "on_torrent_finished": MagicMock(),
        "on_tracker_error": MagicMock(),
        "on_save_resume_data": MagicMock(),
        "on_torrent_removed": MagicMock(),
        "on_torrent_added": MagicMock(),
        "on_storage_moved": MagicMock(),
        "on_file_error": MagicMock(),
    }


@pytest.fixture
def dispatcher(callbacks):
    return AlertDispatcher(
        on_state_update=callbacks["on_state_update"],
        on_metadata_received=callbacks["on_metadata_received"],
        on_torrent_finished=callbacks["on_torrent_finished"],
        on_tracker_error=callbacks["on_tracker_error"],
        on_save_resume_data=callbacks["on_save_resume_data"],
        on_torrent_removed=callbacks["on_torrent_removed"],
        on_torrent_added=callbacks["on_torrent_added"],
        on_storage_moved=callbacks["on_storage_moved"],
        on_file_error=callbacks["on_file_error"],
    )


def _handle_with_hash(info_hash: str) -> MagicMock:
    handle = MagicMock()
    hashes = MagicMock()
    hashes.has_v1.return_value = True
    hashes.v1 = info_hash
    handle.status.return_value.info_hashes = hashes
    return handle


# --------------------------------------------------------------- dispatch()


def test_state_update_alert_forwards_status_list(dispatcher, callbacks):
    alert = MagicMock(spec=lt.state_update_alert)
    alert.status = ["status1", "status2"]

    dispatcher.dispatch(alert)

    callbacks["on_state_update"].assert_called_once_with(["status1", "status2"])


def test_state_update_alert_with_empty_status_list_does_not_fire(dispatcher, callbacks):
    """`if alert.status:` -- an empty list is falsy, so a no-op poll must not
    forward anything."""
    alert = MagicMock(spec=lt.state_update_alert)
    alert.status = []

    dispatcher.dispatch(alert)

    callbacks["on_state_update"].assert_not_called()


def test_metadata_received_alert_extracts_hash(dispatcher, callbacks):
    alert = MagicMock(spec=lt.metadata_received_alert)
    alert.handle = _handle_with_hash("abc123")

    dispatcher.dispatch(alert)

    callbacks["on_metadata_received"].assert_called_once_with("abc123")


def test_torrent_finished_alert_extracts_hash(dispatcher, callbacks):
    alert = MagicMock(spec=lt.torrent_finished_alert)
    alert.handle = _handle_with_hash("def456")

    dispatcher.dispatch(alert)

    callbacks["on_torrent_finished"].assert_called_once_with("def456")


def test_tracker_error_alert_prefers_error_message(dispatcher, callbacks):
    alert = MagicMock(spec=lt.tracker_error_alert)
    alert.handle = _handle_with_hash("hash0")
    alert.error_message = "connection refused"
    alert.message.return_value = "fallback message"

    dispatcher.dispatch(alert)

    callbacks["on_tracker_error"].assert_called_once_with("hash0", "connection refused")


def test_tracker_error_alert_falls_back_to_message_when_error_message_empty(dispatcher, callbacks):
    alert = MagicMock(spec=lt.tracker_error_alert)
    alert.handle = _handle_with_hash("hash0")
    alert.error_message = ""
    alert.message.return_value = "fallback message"

    dispatcher.dispatch(alert)

    callbacks["on_tracker_error"].assert_called_once_with("hash0", "fallback message")


def test_save_resume_data_alert_forwards_hash_and_params(dispatcher, callbacks):
    alert = MagicMock(spec=lt.save_resume_data_alert)
    alert.handle = _handle_with_hash("hash1")
    alert.params = MagicMock()

    dispatcher.dispatch(alert)

    callbacks["on_save_resume_data"].assert_called_once_with("hash1", alert.params)


def test_torrent_removed_alert_uses_info_hashes_directly_not_handle(dispatcher, callbacks):
    """torrent_removed_alert fires after the handle is already gone, so
    dispatch() must read alert.info_hashes directly rather than going
    through handle.status()."""
    alert = MagicMock(spec=lt.torrent_removed_alert)
    hashes = MagicMock()
    hashes.has_v1.return_value = True
    hashes.v1 = "removed-hash"
    alert.info_hashes = hashes

    dispatcher.dispatch(alert)

    callbacks["on_torrent_removed"].assert_called_once_with("removed-hash")


def test_torrent_removed_alert_falls_back_to_v2_hash(dispatcher, callbacks):
    alert = MagicMock(spec=lt.torrent_removed_alert)
    hashes = MagicMock()
    hashes.has_v1.return_value = False
    hashes.v2 = "v2-hash"
    alert.info_hashes = hashes

    dispatcher.dispatch(alert)

    callbacks["on_torrent_removed"].assert_called_once_with("v2-hash")


def test_add_torrent_alert_without_error_fires_callback(dispatcher, callbacks):
    alert = MagicMock(spec=lt.add_torrent_alert)
    alert.error = None
    alert.handle = MagicMock()

    dispatcher.dispatch(alert)

    callbacks["on_torrent_added"].assert_called_once_with(alert.handle)


def test_add_torrent_alert_with_error_does_not_fire_callback(dispatcher, callbacks):
    alert = MagicMock(spec=lt.add_torrent_alert)
    alert.error = MagicMock()  # truthy libtorrent error_code
    alert.handle = MagicMock()

    dispatcher.dispatch(alert)

    callbacks["on_torrent_added"].assert_not_called()


def test_storage_moved_alert_forwards_hash_and_path(dispatcher, callbacks):
    alert = MagicMock(spec=lt.storage_moved_alert)
    alert.handle = _handle_with_hash("hash2")
    alert.storage_path = "D:/new/location"

    dispatcher.dispatch(alert)

    callbacks["on_storage_moved"].assert_called_once_with("hash2", "D:/new/location")


def test_file_error_alert_extracts_hash_and_message(dispatcher, callbacks):
    alert = MagicMock(spec=lt.file_error_alert)
    alert.handle = _handle_with_hash("hash3")
    alert.message.return_value = "torrent: file (path/file.bin): the device is not ready"

    dispatcher.dispatch(alert)

    callbacks["on_file_error"].assert_called_once_with(
        "hash3", "torrent: file (path/file.bin): the device is not ready"
    )


def test_unrecognized_alert_type_triggers_no_callback(dispatcher, callbacks):
    alert = MagicMock(spec=lt.stats_alert)  # not one of the routed types

    dispatcher.dispatch(alert)

    for cb in callbacks.values():
        cb.assert_not_called()


def test_dispatch_all_processes_every_alert_in_order(dispatcher, callbacks):
    alert1 = MagicMock(spec=lt.torrent_finished_alert)
    alert1.handle = _handle_with_hash("hash-a")
    alert2 = MagicMock(spec=lt.torrent_finished_alert)
    alert2.handle = _handle_with_hash("hash-b")

    dispatcher.dispatch_all([alert1, alert2])

    assert callbacks["on_torrent_finished"].call_args_list == [
        (("hash-a",),),
        (("hash-b",),),
    ]


def test_dispatch_all_keeps_processing_after_a_handler_raises(dispatcher, callbacks):
    """Regression for the leaked-torrent-record bug: a state_update_alert
    hitting an already-invalid handle (torrent removed mid-batch) used to
    raise RuntimeError and abort dispatch_all's loop, silently dropping the
    torrent_removed_alert right after it -- so the record/handle were never
    popped. One handler raising must not stop the rest of the batch."""
    bad_alert = MagicMock(spec=lt.state_update_alert)
    bad_alert.status = ["status1"]
    callbacks["on_state_update"].side_effect = RuntimeError("invalid torrent handle used [libtorrent:20]")

    removed_alert = MagicMock(spec=lt.torrent_removed_alert)
    hashes = MagicMock()
    hashes.has_v1.return_value = True
    hashes.v1 = "removed-hash"
    removed_alert.info_hashes = hashes

    dispatcher.dispatch_all([bad_alert, removed_alert])

    callbacks["on_torrent_removed"].assert_called_once_with("removed-hash")


# ----------------------------------------------------------- status_to_record


def _status_stub(**overrides) -> MagicMock:
    hashes = MagicMock()
    hashes.has_v1.return_value = True
    hashes.v1 = "hash0"
    status = MagicMock()
    status.name = "some.torrent"
    status.save_path = "D:/downloads"
    status.total_wanted = 1000
    status.progress = 0.5
    status.download_rate = 1024
    status.upload_rate = 512
    status.num_peers = 3
    status.num_seeds = 2
    status.total_download = 500
    status.total_upload = 250
    status.all_time_download = 5000
    status.all_time_upload = 2500
    status.error = "disk full"
    status.current_tracker = "http://tracker.example/announce"
    status.sequential_download = True
    status.queue_position = 4
    status.has_metadata = True
    status.paused = False
    status.state = "downloading"
    status.info_hashes = hashes
    for key, value in overrides.items():
        setattr(status, key, value)
    return status


def test_status_to_record_copies_every_field():
    status = _status_stub()
    record = TorrentRecord(info_hash="hash0", name="old-name")

    status_to_record(status, record)

    assert record.name == "some.torrent"
    assert record.save_path == "D:/downloads"
    assert record.total_size == 1000
    assert record.progress == 0.5
    assert record.download_rate == 1024
    assert record.upload_rate == 512
    assert record.num_peers == 3
    assert record.num_seeds == 2
    assert record.total_downloaded == 500
    assert record.total_uploaded == 250
    assert record.all_time_downloaded == 5000
    assert record.all_time_uploaded == 2500
    assert record.error == "disk full"
    assert record.current_tracker == "http://tracker.example/announce"
    assert record.sequential_download is True
    assert record.queue_position == 4
    assert record.is_magnet_awaiting_metadata is False
    assert record.state == TorrentState.DOWNLOADING


def test_status_to_record_keeps_previous_name_when_status_name_is_empty():
    status = _status_stub(name="")
    record = TorrentRecord(info_hash="hash0", name="kept-name")

    status_to_record(status, record)

    assert record.name == "kept-name"


def test_status_to_record_defaults_error_to_empty_string_when_falsy():
    status = _status_stub(error=None)
    record = TorrentRecord(info_hash="hash0")

    status_to_record(status, record)

    assert record.error == ""


def test_status_to_record_sets_awaiting_metadata_when_no_metadata_yet():
    status = _status_stub(has_metadata=False)
    record = TorrentRecord(info_hash="hash0")

    status_to_record(status, record)

    assert record.is_magnet_awaiting_metadata is True
    assert record.state == TorrentState.CHECKING_METADATA


def test_status_to_record_queue_position_is_coerced_to_int():
    status = _status_stub(queue_position=7.0)
    record = TorrentRecord(info_hash="hash0")

    status_to_record(status, record)

    assert record.queue_position == 7
    assert isinstance(record.queue_position, int)
