"""Security Center: a read-only overview that aggregates session security/
privacy state which today is scattered across three separate screens --
ProfileTab's Security and Network/Privacy sections, and the danger-report
column that's only visible while a torrent is actually being analyzed in the
Add tab. Nothing here is new data -- every value is read straight off the
same Settings and SessionManager.all_records() those other screens already
read from.

Follows the profile_sections.py convention (see that module's docstring for
the full live-apply vs save-on-click rationale): a self-contained QGroupBox
with retranslate_ui() and write_to(settings). This section only ever reads,
so write_to() is a no-op.
"""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord
from torrent2000.i18n.translator import tr

# Matches the RiskLevel palette already established in file_tree_risk.py, so
# "protection is on / partial / off" reads with the same visual language
# wherever it shows up in the app.
_COLOR_GOOD = QColor(60, 160, 60)
_COLOR_WARN = QColor(200, 140, 30)
_COLOR_BAD = QColor(180, 30, 30)

# libtorrent's "enabled" mode still allows a plaintext fallback -- a real but
# partial protection, distinct from "forced" (full) and "disabled" (none).
_ENCRYPTION_LABEL_KEYS = {
    "forced": "encryption_mode.forced",
    "enabled": "encryption_mode.enabled",
    "disabled": "encryption_mode.disabled",
}
_ENCRYPTION_COLORS = {
    "forced": _COLOR_GOOD,
    "enabled": _COLOR_WARN,
    "disabled": _COLOR_BAD,
}


def _add_row(form: QFormLayout, form_labels: dict[str, QLabel], key: str, field) -> None:
    label = QLabel(tr(key), form.parentWidget())
    form_labels[key] = label
    form.addRow(label, field)


def _set_status(label: QLabel, active: bool) -> None:
    label.setText(tr("security_center.status_active") if active else tr("security_center.status_inactive"))
    color = _COLOR_GOOD if active else _COLOR_BAD
    label.setStyleSheet(f"color: rgb({color.red()}, {color.green()}, {color.blue()}); font-weight: bold;")


def _clear_style(label: QLabel) -> None:
    label.setStyleSheet("")


def risk_report_summary(session_manager: SessionManager) -> tuple[int, int]:
    """Returns (scanned_count, flagged_count) across every torrent currently
    known to the session. "Flagged" mirrors danger_scanner.scanner's own
    definition of a risky torrent (ScanResult.flagged_indices is non-empty,
    i.e. at least one file scored RiskLevel.MEDIUM or above) rather than
    inventing a separate threshold here."""
    records: list[TorrentRecord] = session_manager.all_records()
    scanned = [record for record in records if record.danger_report is not None]
    flagged = [record for record in scanned if record.danger_report.flagged_indices]
    return len(scanned), len(flagged)


class SecurityCenterSection(QGroupBox):
    """Read-only snapshot of the session's security/privacy posture: proxy
    kill switch, DHT/PEX/LSD discovery restriction, protocol encryption,
    bound network interface, and a summary of danger-scan results across
    every currently known torrent. A "Refresh" button rebuilds the whole
    display from settings/session_manager on demand, since none of this data
    pushes change notifications of its own to this widget."""

    def __init__(self, settings: Settings, session_manager: SessionManager, parent=None) -> None:
        super().__init__(tr("security_center.group"), parent)
        self._settings = settings
        self._session_manager = session_manager
        self._form_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)

        self.intro_label = QLabel(tr("security_center.intro"), self)
        self.intro_label.setWordWrap(True)
        layout.addWidget(self.intro_label)

        form = QFormLayout()
        layout.addLayout(form)

        self.proxy_status_label = QLabel(self)
        _add_row(form, self._form_labels, "security_center.proxy_row_label", self.proxy_status_label)

        self.proxy_note_label = QLabel(self)
        self.proxy_note_label.setWordWrap(True)
        layout.addWidget(self.proxy_note_label)

        self.discovery_status_label = QLabel(self)
        _add_row(form, self._form_labels, "security_center.discovery_row_label", self.discovery_status_label)
        self.discovery_status_label.setToolTip(tr("profile_tab.restrict_discovery_tooltip"))

        self.encryption_status_label = QLabel(self)
        _add_row(form, self._form_labels, "security_center.encryption_row_label", self.encryption_status_label)
        self.encryption_status_label.setToolTip(tr("profile_tab.encryption_tooltip"))

        self.interface_status_label = QLabel(self)
        _add_row(form, self._form_labels, "security_center.interface_row_label", self.interface_status_label)

        self.risk_status_label = QLabel(self)
        _add_row(form, self._form_labels, "security_center.risk_row_label", self.risk_status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.refresh_button = QPushButton(tr("security_center.refresh_button"), self)
        self.refresh_button.clicked.connect(self.refresh)
        button_row.addWidget(self.refresh_button)
        layout.addLayout(button_row)

        self.refresh()

    def retranslate_ui(self) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))
        self.setTitle(tr("security_center.group"))
        self.intro_label.setText(tr("security_center.intro"))
        self.discovery_status_label.setToolTip(tr("profile_tab.restrict_discovery_tooltip"))
        self.encryption_status_label.setToolTip(tr("profile_tab.encryption_tooltip"))
        self.refresh_button.setText(tr("security_center.refresh_button"))
        self.refresh()

    def write_to(self, settings: Settings) -> None:
        pass  # read-only display, nothing to persist

    def refresh(self) -> None:
        """Rebuilds every value shown in the section from the current
        settings/session_manager state -- called on construction, after a
        language change, and whenever the user clicks "Refresh" (useful
        after adding/removing a torrent or changing settings elsewhere)."""
        proxy = self._settings.proxy
        _set_status(self.proxy_status_label, proxy.enabled)
        if not proxy.enabled:
            self.proxy_note_label.setText(tr("security_center.proxy_disabled_note"))
        elif proxy.force_proxy:
            self.proxy_note_label.setText(tr("security_center.kill_switch_active_note"))
        else:
            self.proxy_note_label.setText(tr("security_center.kill_switch_inactive_note"))

        _set_status(self.discovery_status_label, self._settings.restrict_discovery)

        mode = self._settings.encryption_mode
        self.encryption_status_label.setText(tr(_ENCRYPTION_LABEL_KEYS.get(mode, "encryption_mode.enabled")))
        color = _ENCRYPTION_COLORS.get(mode, _COLOR_WARN)
        self.encryption_status_label.setStyleSheet(
            f"color: rgb({color.red()}, {color.green()}, {color.blue()}); font-weight: bold;"
        )

        self.interface_status_label.setText(self._settings.network_interface or tr("profile_tab.interface_default"))
        _clear_style(self.interface_status_label)

        scanned, flagged = risk_report_summary(self._session_manager)
        if scanned == 0:
            self.risk_status_label.setText(tr("security_center.risk_no_scans"))
            _clear_style(self.risk_status_label)
        else:
            self.risk_status_label.setText(tr("security_center.risk_summary", scanned=scanned, flagged=flagged))
            color = _COLOR_BAD if flagged > 0 else _COLOR_GOOD
            self.risk_status_label.setStyleSheet(
                f"color: rgb({color.red()}, {color.green()}, {color.blue()}); font-weight: bold;"
            )
