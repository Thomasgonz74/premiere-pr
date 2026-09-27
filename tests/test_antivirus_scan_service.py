import subprocess
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.antivirus_scan_service import AntivirusScanService, find_mpcmdrun


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@dataclass
class FakeRecord:
    info_hash: str = "abc"
    save_path: str = "C:\\Downloads\\some-torrent"
    name: str = ""


class FakeSessionManager(QObject):
    torrent_finished = Signal(str)

    def __init__(self):
        super().__init__()
        self.records: dict = {}

    def get_record(self, info_hash: str):
        return self.records.get(info_hash)


# --------------------------------------------------------------------- service


def test_disabled_by_default_never_submits_a_scan():
    settings = Settings()
    assert settings.scan_completed_files_with_defender is False

    fake_sm = FakeSessionManager()
    fake_sm.records["abc"] = FakeRecord()
    service = AntivirusScanService(fake_sm, settings)

    with patch("torrent2000.engine.antivirus_scan_service.QThreadPool") as mock_pool_cls:
        fake_sm.torrent_finished.emit("abc")
        mock_pool_cls.globalInstance.assert_not_called()


def test_submits_scan_runnable_when_enabled_and_torrent_finishes():
    settings = Settings()
    settings.scan_completed_files_with_defender = True

    fake_sm = FakeSessionManager()
    fake_sm.records["abc"] = FakeRecord(save_path="C:\\Downloads\\my-torrent")
    service = AntivirusScanService(fake_sm, settings)

    mock_start = MagicMock()
    with patch("torrent2000.engine.antivirus_scan_service.QThreadPool") as mock_pool_cls:
        mock_pool_cls.globalInstance.return_value.start = mock_start
        fake_sm.torrent_finished.emit("abc")

    mock_start.assert_called_once()
    submitted_runnable = mock_start.call_args[0][0]
    assert submitted_runnable._save_path == "C:\\Downloads\\my-torrent"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("My.Torrent", "My.Torrent"),  # the torrent's own folder, not the whole library
        ("..", None),  # crafted name escaping save_path: confinement refuses it
        ("Missing.Torrent", None),  # not on disk (e.g. renamed): scan save_path instead
        ("", None),
    ],
)
def test_scans_the_torrents_own_folder_rather_than_the_shared_save_path(tmp_path, name, expected):
    (tmp_path / "My.Torrent").mkdir()
    settings = Settings()
    settings.scan_completed_files_with_defender = True
    fake_sm = FakeSessionManager()
    fake_sm.records["abc"] = FakeRecord(save_path=str(tmp_path), name=name)
    service = AntivirusScanService(fake_sm, settings)

    mock_start = MagicMock()
    with patch("torrent2000.engine.antivirus_scan_service.QThreadPool") as mock_pool_cls:
        mock_pool_cls.globalInstance.return_value.start = mock_start
        fake_sm.torrent_finished.emit("abc")

    submitted_runnable = mock_start.call_args[0][0]
    assert submitted_runnable._save_path == str(tmp_path / expected if expected else tmp_path)


def test_no_scan_when_record_missing():
    settings = Settings()
    settings.scan_completed_files_with_defender = True

    fake_sm = FakeSessionManager()  # no records at all
    service = AntivirusScanService(fake_sm, settings)

    with patch("torrent2000.engine.antivirus_scan_service.QThreadPool") as mock_pool_cls:
        fake_sm.torrent_finished.emit("missing-hash")
        mock_pool_cls.globalInstance.assert_not_called()


def test_no_scan_when_record_has_no_save_path():
    settings = Settings()
    settings.scan_completed_files_with_defender = True

    fake_sm = FakeSessionManager()
    fake_sm.records["abc"] = FakeRecord(save_path="")
    service = AntivirusScanService(fake_sm, settings)

    with patch("torrent2000.engine.antivirus_scan_service.QThreadPool") as mock_pool_cls:
        fake_sm.torrent_finished.emit("abc")
        mock_pool_cls.globalInstance.assert_not_called()


# ------------------------------------------------------------ find_mpcmdrun


def test_find_mpcmdrun_prefers_path():
    with patch("torrent2000.engine.antivirus_scan_service.shutil.which", return_value="C:\\PATH\\MpCmdRun.exe"):
        assert find_mpcmdrun() == "C:\\PATH\\MpCmdRun.exe"


def test_find_mpcmdrun_falls_back_to_classic_path():
    fake_classic = MagicMock()
    fake_classic.exists.return_value = True
    fake_classic.__str__.return_value = "C:\\Program Files\\Windows Defender\\MpCmdRun.exe"

    with (
        patch("torrent2000.engine.antivirus_scan_service.shutil.which", return_value=None),
        patch("torrent2000.engine.antivirus_scan_service._CLASSIC_MPCMDRUN_PATH", fake_classic),
    ):
        assert find_mpcmdrun() == "C:\\Program Files\\Windows Defender\\MpCmdRun.exe"


def test_find_mpcmdrun_falls_back_to_newest_platform_glob():
    older = MagicMock()
    older.parent.name = "4.18.2109.6"
    newer = MagicMock()
    newer.parent.name = "4.18.2211.5"
    newer.__str__.return_value = "C:\\ProgramData\\Microsoft\\Windows Defender\\platform\\4.18.2211.5\\MpCmdRun.exe"

    fake_classic = MagicMock()
    fake_classic.exists.return_value = False

    fake_platform_dir = MagicMock()
    fake_platform_dir.glob.return_value = [older, newer]

    with (
        patch("torrent2000.engine.antivirus_scan_service.shutil.which", return_value=None),
        patch("torrent2000.engine.antivirus_scan_service._CLASSIC_MPCMDRUN_PATH", fake_classic),
        patch("torrent2000.engine.antivirus_scan_service._PLATFORM_DIR", fake_platform_dir),
    ):
        result = find_mpcmdrun()

    assert result == "C:\\ProgramData\\Microsoft\\Windows Defender\\platform\\4.18.2211.5\\MpCmdRun.exe"


def test_find_mpcmdrun_returns_none_when_nothing_found():
    fake_classic = MagicMock()
    fake_classic.exists.return_value = False
    fake_platform_dir = MagicMock()
    fake_platform_dir.glob.return_value = []

    with (
        patch("torrent2000.engine.antivirus_scan_service.shutil.which", return_value=None),
        patch("torrent2000.engine.antivirus_scan_service._CLASSIC_MPCMDRUN_PATH", fake_classic),
        patch("torrent2000.engine.antivirus_scan_service._PLATFORM_DIR", fake_platform_dir),
    ):
        assert find_mpcmdrun() is None


# --------------------------------------------------------------------- _ScanRunnable


def test_scan_runnable_logs_warning_and_returns_when_mpcmdrun_missing():
    from torrent2000.engine.antivirus_scan_service import _ScanRunnable

    runnable = _ScanRunnable("C:\\Downloads\\some-torrent")
    with (
        patch("torrent2000.engine.antivirus_scan_service.find_mpcmdrun", return_value=None),
        patch("torrent2000.engine.antivirus_scan_service.subprocess.Popen") as mock_popen,
    ):
        runnable.run()
        mock_popen.assert_not_called()


def test_scan_runnable_invokes_mpcmdrun_with_expected_args():
    from torrent2000.engine.antivirus_scan_service import _ScanRunnable

    runnable = _ScanRunnable("C:\\Downloads\\some-torrent")
    with (
        patch("torrent2000.engine.antivirus_scan_service.find_mpcmdrun", return_value="C:\\MpCmdRun.exe"),
        patch("torrent2000.engine.antivirus_scan_service.subprocess.Popen") as mock_popen,
    ):
        mock_popen.return_value.wait.return_value = 0
        runnable.run()

    mock_popen.assert_called_once_with(
        ["C:\\MpCmdRun.exe", "-Scan", "-ScanType", "3", "-File", "C:\\Downloads\\some-torrent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    mock_popen.return_value.kill.assert_not_called()


def test_scan_runnable_swallows_timeout_without_raising():
    from torrent2000.engine.antivirus_scan_service import _ScanRunnable

    runnable = _ScanRunnable("C:\\Downloads\\some-torrent")
    with (
        patch("torrent2000.engine.antivirus_scan_service.find_mpcmdrun", return_value="C:\\MpCmdRun.exe"),
        patch("torrent2000.engine.antivirus_scan_service.subprocess.Popen") as mock_popen,
    ):
        mock_popen.return_value.wait.side_effect = subprocess.TimeoutExpired(cmd="MpCmdRun.exe", timeout=1)
        runnable.run()  # must not raise

    assert mock_popen.return_value.wait.call_count == 300  # SCAN_TIMEOUT_SECONDS one-second waits
    mock_popen.return_value.kill.assert_called_once()


def test_scan_runnable_is_killed_within_a_second_of_quit(monkeypatch):
    # Qt keeps the process alive until every running pool task returns --
    # a scan must not hold Quit for up to SCAN_TIMEOUT_SECONDS.
    import threading

    import torrent2000.engine.antivirus_scan_service as antivirus_module
    from torrent2000.engine.antivirus_scan_service import _ScanRunnable

    monkeypatch.setattr(antivirus_module, "_cancel_event", threading.Event())

    def wait(timeout):
        antivirus_module.cancel_running_scans()  # Quit arrives during the first second
        raise subprocess.TimeoutExpired(cmd="MpCmdRun.exe", timeout=timeout)

    runnable = _ScanRunnable("C:\\Downloads\\some-torrent")
    with (
        patch("torrent2000.engine.antivirus_scan_service.find_mpcmdrun", return_value="C:\\MpCmdRun.exe"),
        patch("torrent2000.engine.antivirus_scan_service.subprocess.Popen") as mock_popen,
    ):
        mock_popen.return_value.wait.side_effect = wait
        runnable.run()

    assert mock_popen.return_value.wait.call_count == 1
    mock_popen.return_value.kill.assert_called_once()


def test_scan_runnable_swallows_oserror_without_raising():
    from torrent2000.engine.antivirus_scan_service import _ScanRunnable

    runnable = _ScanRunnable("C:\\Downloads\\some-torrent")
    with (
        patch("torrent2000.engine.antivirus_scan_service.find_mpcmdrun", return_value="C:\\MpCmdRun.exe"),
        patch("torrent2000.engine.antivirus_scan_service.subprocess.Popen", side_effect=OSError("boom")),
    ):
        runnable.run()  # must not raise
