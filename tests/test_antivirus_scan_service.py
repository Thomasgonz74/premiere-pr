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
        patch("torrent2000.engine.antivirus_scan_service.subprocess.run") as mock_run,
    ):
        runnable.run()
        mock_run.assert_not_called()


def test_scan_runnable_invokes_mpcmdrun_with_expected_args():
    from torrent2000.engine.antivirus_scan_service import _ScanRunnable

    runnable = _ScanRunnable("C:\\Downloads\\some-torrent")
    with (
        patch("torrent2000.engine.antivirus_scan_service.find_mpcmdrun", return_value="C:\\MpCmdRun.exe"),
        patch("torrent2000.engine.antivirus_scan_service.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        runnable.run()

    mock_run.assert_called_once_with(
        ["C:\\MpCmdRun.exe", "-Scan", "-ScanType", "3", "-File", "C:\\Downloads\\some-torrent"],
        capture_output=True,
        timeout=300,
        check=False,
    )


def test_scan_runnable_swallows_timeout_without_raising():
    import subprocess

    from torrent2000.engine.antivirus_scan_service import _ScanRunnable

    runnable = _ScanRunnable("C:\\Downloads\\some-torrent")
    with (
        patch("torrent2000.engine.antivirus_scan_service.find_mpcmdrun", return_value="C:\\MpCmdRun.exe"),
        patch(
            "torrent2000.engine.antivirus_scan_service.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="MpCmdRun.exe", timeout=300),
        ),
    ):
        runnable.run()  # must not raise


def test_scan_runnable_swallows_oserror_without_raising():
    from torrent2000.engine.antivirus_scan_service import _ScanRunnable

    runnable = _ScanRunnable("C:\\Downloads\\some-torrent")
    with (
        patch("torrent2000.engine.antivirus_scan_service.find_mpcmdrun", return_value="C:\\MpCmdRun.exe"),
        patch("torrent2000.engine.antivirus_scan_service.subprocess.run", side_effect=OSError("boom")),
    ):
        runnable.run()  # must not raise
