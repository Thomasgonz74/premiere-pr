from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from torrent2000.danger_scanner.models import RiskLevel, ScanResult
from torrent2000.i18n.translator import tr
from torrent2000.utils.formatting import human_size

_LEVEL_LABEL_KEYS = {
    RiskLevel.SAFE: "file_tree_risk.level_safe",
    RiskLevel.LOW: "file_tree_risk.level_low",
    RiskLevel.MEDIUM: "file_tree_risk.level_medium",
    RiskLevel.HIGH: "file_tree_risk.level_high",
    RiskLevel.CRITICAL: "file_tree_risk.level_critical",
}

_LEVEL_COLORS = {
    RiskLevel.SAFE: QColor(60, 160, 60),
    RiskLevel.LOW: QColor(150, 150, 40),
    RiskLevel.MEDIUM: QColor(200, 140, 30),
    RiskLevel.HIGH: QColor(200, 80, 30),
    RiskLevel.CRITICAL: QColor(180, 30, 30),
}


class FileTreeRiskWidget(QTreeWidget):
    """Checkable file list sorted by risk score (highest first). Checked = will
    be downloaded; unchecked = excluded ("cleaned")."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(4)
        self._apply_header_labels()
        self.setSortingEnabled(False)
        self.setRootIsDecorated(False)
        self.header().setStretchLastSection(True)

    def _apply_header_labels(self) -> None:
        self.setHeaderLabels(
            [
                tr("file_tree_risk.column_file"),
                tr("file_tree_risk.column_size"),
                tr("file_tree_risk.column_risk"),
                tr("file_tree_risk.column_reasons"),
            ]
        )

    def retranslate_ui(self) -> None:
        self._apply_header_labels()

    def load_scan_result(self, result: ScanResult, auto_exclude_threshold: int) -> None:
        self.clear()
        ordered = sorted(result.file_risks, key=lambda fr: fr.score, reverse=True)
        for file_risk in ordered:
            item = QTreeWidgetItem(
                [
                    file_risk.file.path,
                    human_size(file_risk.file.size),
                    tr(_LEVEL_LABEL_KEYS[file_risk.level]),
                    "; ".join(file_risk.reasons) if file_risk.reasons else "",
                ]
            )
            item.setData(0, Qt.UserRole, file_risk.file.index)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            checked = file_risk.score < auto_exclude_threshold
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            color = _LEVEL_COLORS.get(file_risk.level)
            if color is not None and file_risk.level != RiskLevel.SAFE:
                for col in range(4):
                    item.setForeground(col, QBrush(color))
            self.addTopLevelItem(item)
        for col in range(3):
            self.resizeColumnToContents(col)

    def excluded_indices(self) -> set[int]:
        excluded = set()
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.checkState(0) == Qt.Unchecked:
                excluded.add(item.data(0, Qt.UserRole))
        return excluded

    def check_all(self) -> None:
        for i in range(self.topLevelItemCount()):
            self.topLevelItem(i).setCheckState(0, Qt.Checked)

    def uncheck_all(self) -> None:
        for i in range(self.topLevelItemCount()):
            self.topLevelItem(i).setCheckState(0, Qt.Unchecked)
