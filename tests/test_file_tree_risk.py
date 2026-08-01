import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.danger_scanner.models import FileEntry, FileRisk, RiskLevel, ScanResult
from torrent2000.ui.widgets.file_tree_risk import FileTreeRiskWidget


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_scan_result() -> ScanResult:
    files = [
        FileEntry(index=0, path="Movie.mkv", size=1_000_000),
        FileEntry(index=1, path="Subtitles/en.srt", size=1024),
        FileEntry(index=2, path="Subtitles/fr.srt", size=1024),
        FileEntry(index=3, path="readme.exe", size=2048, executable_flag=True),
    ]
    file_risks = [
        FileRisk(file=files[0], score=0, level=RiskLevel.SAFE, reasons=[]),
        FileRisk(file=files[1], score=0, level=RiskLevel.SAFE, reasons=[]),
        FileRisk(file=files[2], score=0, level=RiskLevel.SAFE, reasons=[]),
        FileRisk(file=files[3], score=90, level=RiskLevel.CRITICAL, reasons=["executable"]),
    ]
    return ScanResult(file_risks=file_risks, overall_score=90, flagged_indices=[3])


def test_check_all_leaves_no_excluded_indices():
    widget = FileTreeRiskWidget()
    widget.load_scan_result(_make_scan_result(), auto_exclude_threshold=50)

    # The high-risk file starts auto-excluded by the threshold.
    assert widget.excluded_indices() == {3}

    widget.check_all()

    assert widget.excluded_indices() == set()


def test_uncheck_all_excludes_every_index():
    widget = FileTreeRiskWidget()
    widget.load_scan_result(_make_scan_result(), auto_exclude_threshold=50)

    widget.uncheck_all()

    assert widget.excluded_indices() == {0, 1, 2, 3}
