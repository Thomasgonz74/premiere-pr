"""ProfileTab's settings sections, each a self-contained QGroupBox owning its
own widgets, retranslate_ui(), and read/write access to Settings.

profile_tab.py used to build all ten of these inline in one constructor with
one giant _on_save_clicked -- this split keeps each section's widgets, labels,
and Settings-writing logic together, so adding a new setting only ever means
touching the one section it belongs to.

Live-apply vs save-on-click convention: every control here is save-on-click
by default -- it only takes effect once the user clicks the Save button at
the bottom of the tab, which calls each section's write_to(settings) in turn
(see ProfileTab._on_save_clicked). The three exceptions are theme,
appearance_mode, and language in GeneralSettingsSection, and volume in
AudioSection: these apply and persist immediately on change, with no Save
click needed. That's a deliberate exception, not an oversight -- each is a
one-click, instantly-visible/audible preview (a picker choice, a slider drag)
rather than a multi-field setting (proxy host+port+credentials, a bandwidth
window's start/end hours) that benefits from being reviewed as a whole and
committed together. RssTab's per-row "enabled" checkbox follows the same
live-apply reasoning for the same reason (a single toggle, not a multi-field
form) -- see its _on_enabled_toggled.
"""

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path

import psutil
from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from torrent2000.config.paths import get_config_path, get_logs_dir
from torrent2000.config.settings import BandwidthSchedule, ProxySettings, RssFeedSubscription, Settings, _from_dict
from torrent2000.engine import startup_registration
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor
from torrent2000.engine.session_manager import SessionManager
from torrent2000.i18n.translator import LANGUAGE_LABELS, set_language, tr
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.leveling import UPLOAD_LEVEL_WEIGHT, score_factors_for, weighted_total_bytes
from torrent2000.stats.models import StatsSnapshot
from torrent2000.stats.service import StatsService
from torrent2000.theme_ids import CCCP_THEME_ID, MACOS_THEME_ID
from torrent2000.ui.theme.theme_manager import THEME_LABELS, appearance_mode_labels
from torrent2000.utils.formatting import human_size

logger = logging.getLogger(__name__)

# Shown once, right when the user switches TO one of these joke themes, so
# the rule changes they're about to hit aren't a silent surprise.
_THEME_SWITCH_NOTICE_KEYS = {
    MACOS_THEME_ID: ("cccp.macos_notice_title", "cccp.macos_notice_message"),
    CCCP_THEME_ID: ("cccp.notice_title", "cccp.notice_message"),
}


def _add_row(form: QFormLayout, form_labels: dict[str, QLabel], key: str, field) -> None:
    label = QLabel(tr(key), form.parentWidget())
    form_labels[key] = label
    form.addRow(label, field)


def _populate_combo(combo: QComboBox, labels: list[tuple[str, str]], current_value: str) -> None:
    combo.blockSignals(True)
    combo.clear()
    for label, value in labels:
        combo.addItem(label, value)
    idx = combo.findData(current_value)
    combo.setCurrentIndex(max(0, idx))
    combo.blockSignals(False)


def _proxy_type_labels() -> list[tuple[str, str]]:
    return [
        (tr("proxy_type.none"), "none"),
        (tr("proxy_type.socks5"), "socks5"),
        (tr("proxy_type.socks5_pw"), "socks5_pw"),
        (tr("proxy_type.http"), "http"),
        (tr("proxy_type.http_pw"), "http_pw"),
    ]


def _encryption_mode_labels() -> list[tuple[str, str]]:
    return [
        (tr("encryption_mode.disabled"), "disabled"),
        (tr("encryption_mode.enabled"), "enabled"),
        (tr("encryption_mode.forced"), "forced"),
    ]


def _shutdown_action_labels() -> list[tuple[str, str]]:
    return [
        (tr("shutdown_action.shutdown"), "shutdown"),
        (tr("shutdown_action.hibernate"), "hibernate"),
    ]


def _list_local_ipv4_interfaces() -> list[tuple[str, str]]:
    """Returns (display_label, ip_address) pairs for non-loopback IPv4
    adapters, so the user can bind outgoing torrent traffic to a specific
    network adapter (e.g. a VPN's virtual adapter) for IP masking."""
    entries = []
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if getattr(addr.family, "name", "") == "AF_INET" and not addr.address.startswith("127."):
                entries.append((f"{name} ({addr.address})", addr.address))
                break
    return entries


def _list_local_ipv6_interfaces() -> list[tuple[str, str]]:
    """Same purpose as _list_local_ipv4_interfaces but for the AF_INET6
    family. Link-local addresses (fe80::/10, and "::1" loopback) are
    excluded -- they're scoped to a single link/host and useless as a
    libtorrent bind address."""
    entries = []
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if (
                getattr(addr.family, "name", "") == "AF_INET6"
                and not addr.address.startswith("fe80:")
                and addr.address != "::1"
            ):
                entries.append((f"{name} ({addr.address})", addr.address))
                break
    return entries


class GeneralSettingsSection(QGroupBox):
    """Default download dir, rate limits, danger threshold, theme/appearance/
    language pickers, notifications, launch-at-startup, update checking."""

    theme_changed = Signal(str, str)  # theme_id, appearance_mode
    language_changed = Signal(str)  # language code

    def __init__(self, settings: Settings, session_manager: SessionManager, parent=None) -> None:
        super().__init__(tr("profile_tab.general_group"), parent)
        self._settings = settings
        self._session_manager = session_manager
        self._form_labels: dict[str, QLabel] = {}
        form = QFormLayout(self)

        dest_row = QHBoxLayout()
        self.dest_input = QLineEdit(settings.default_download_dir, self)
        dest_row.addWidget(self.dest_input)
        self.dest_browse_button = QPushButton(tr("common.browse"), self)
        self.dest_browse_button.clicked.connect(self._on_browse_dest)
        dest_row.addWidget(self.dest_browse_button)
        _add_row(form, self._form_labels, "profile_tab.default_download_dir", dest_row)

        self.download_limit_spin = QSpinBox(self)
        self.download_limit_spin.setRange(0, 1_000_000)
        self.download_limit_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.download_limit_spin.setValue(settings.download_rate_limit_kbps)
        _add_row(form, self._form_labels, "profile_tab.download_limit", self.download_limit_spin)

        self.upload_limit_spin = QSpinBox(self)
        self.upload_limit_spin.setRange(0, 1_000_000)
        self.upload_limit_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.upload_limit_spin.setValue(settings.upload_rate_limit_kbps)
        _add_row(form, self._form_labels, "profile_tab.upload_limit", self.upload_limit_spin)

        self.max_active_downloads_spin = QSpinBox(self)
        self.max_active_downloads_spin.setRange(1, 100)
        self.max_active_downloads_spin.setValue(settings.max_active_downloads)
        _add_row(form, self._form_labels, "profile_tab.max_active_downloads", self.max_active_downloads_spin)

        self.danger_threshold_spin = QSpinBox(self)
        self.danger_threshold_spin.setRange(0, 100)
        self.danger_threshold_spin.setValue(settings.danger_auto_exclude_threshold)
        _add_row(form, self._form_labels, "profile_tab.danger_threshold", self.danger_threshold_spin)

        self.theme_combo = QComboBox(self)
        for label, theme_id in THEME_LABELS:
            self.theme_combo.addItem(label, theme_id)
        idx = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(0, idx))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        _add_row(form, self._form_labels, "profile_tab.theme_label", self.theme_combo)

        self.appearance_combo = QComboBox(self)
        _populate_combo(self.appearance_combo, appearance_mode_labels(), settings.appearance_mode)
        self.appearance_combo.currentIndexChanged.connect(self._on_appearance_changed)
        _add_row(form, self._form_labels, "profile_tab.appearance_mode_label", self.appearance_combo)

        self.language_combo = QComboBox(self)
        # Each language's own name is always shown in that language itself
        # (autonym), never translated -- "Français"/"English"/"Русский"
        # stay the same no matter which language is currently active, the
        # same convention every OS/app language picker already uses.
        _populate_combo(self.language_combo, LANGUAGE_LABELS, settings.language)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        _add_row(form, self._form_labels, "profile_tab.language_label", self.language_combo)

        self.notifications_checkbox = QCheckBox(tr("profile_tab.notifications_checkbox"), self)
        self.notifications_checkbox.setChecked(settings.notifications_enabled)
        form.addRow(self.notifications_checkbox)

        self.launch_at_startup_checkbox = QCheckBox(tr("profile_tab.launch_at_startup_checkbox"), self)
        # Reflects the real HKCU Run key rather than the possibly-stale saved
        # setting -- if the user (or a reinstall) removed it by hand, this
        # should show unchecked rather than lying about it.
        self.launch_at_startup_checkbox.setChecked(startup_registration.is_launch_at_startup_enabled())
        form.addRow(self.launch_at_startup_checkbox)

        self.check_for_updates_checkbox = QCheckBox(tr("profile_tab.check_for_updates_checkbox"), self)
        self.check_for_updates_checkbox.setChecked(settings.check_for_updates)
        form.addRow(self.check_for_updates_checkbox)

        self.minimize_to_tray_checkbox = QCheckBox(tr("profile_tab.minimize_to_tray_checkbox"), self)
        self.minimize_to_tray_checkbox.setChecked(settings.minimize_to_tray)
        form.addRow(self.minimize_to_tray_checkbox)

    def retranslate_ui(self) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))
        self.setTitle(tr("profile_tab.general_group"))
        self.dest_browse_button.setText(tr("common.browse"))
        self.download_limit_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.upload_limit_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        _populate_combo(self.appearance_combo, appearance_mode_labels(), self._settings.appearance_mode)
        self.notifications_checkbox.setText(tr("profile_tab.notifications_checkbox"))
        self.launch_at_startup_checkbox.setText(tr("profile_tab.launch_at_startup_checkbox"))
        self.check_for_updates_checkbox.setText(tr("profile_tab.check_for_updates_checkbox"))
        self.minimize_to_tray_checkbox.setText(tr("profile_tab.minimize_to_tray_checkbox"))

    def write_to(self, settings: Settings) -> None:
        settings.default_download_dir = self.dest_input.text().strip() or settings.default_download_dir
        settings.download_rate_limit_kbps = self.download_limit_spin.value()
        settings.upload_rate_limit_kbps = self.upload_limit_spin.value()
        settings.max_active_downloads = self.max_active_downloads_spin.value()
        settings.danger_auto_exclude_threshold = self.danger_threshold_spin.value()
        settings.notifications_enabled = self.notifications_checkbox.isChecked()
        settings.launch_at_startup = self.launch_at_startup_checkbox.isChecked()
        startup_registration.set_launch_at_startup(settings.launch_at_startup)
        settings.check_for_updates = self.check_for_updates_checkbox.isChecked()
        settings.minimize_to_tray = self.minimize_to_tray_checkbox.isChecked()
        # theme/appearance_mode/language are intentionally NOT written here --
        # they live-apply and persist immediately on change (see below).

    def _on_browse_dest(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("profile_tab.choose_dest_dir_title"), self.dest_input.text())
        if directory:
            self.dest_input.setText(directory)

    def _on_theme_changed(self, index: int) -> None:
        theme_id = self.theme_combo.itemData(index)
        if not theme_id:
            return
        # Applied immediately (live preview) rather than gated behind the
        # "Enregistrer" button -- a theme picker only really makes sense as
        # an instant switch, and it's low-stakes enough to persist right away.
        self._settings.theme = theme_id
        self._settings.save()
        # CCCP's "no downloading" rule takes effect immediately, pausing
        # any in-progress downloads -- MainWindow shows the "N paused"
        # notice reactively via SessionManager.theme_downloads_paused.
        self._session_manager.enforce_theme_download_policy()
        self.theme_changed.emit(theme_id, self._settings.appearance_mode)
        notice_keys = _THEME_SWITCH_NOTICE_KEYS.get(theme_id)
        if notice_keys:
            title_key, message_key = notice_keys
            QMessageBox.information(self, tr(title_key), tr(message_key))

    def _on_appearance_changed(self, index: int) -> None:
        mode_id = self.appearance_combo.itemData(index)
        if not mode_id:
            return
        self._settings.appearance_mode = mode_id
        self._settings.save()
        self.theme_changed.emit(self._settings.theme, mode_id)

    def _on_language_changed(self, index: int) -> None:
        language_code = self.language_combo.itemData(index)
        if not language_code:
            return
        self._settings.language = language_code
        self._settings.save()
        set_language(language_code)
        self.language_changed.emit(language_code)


class AudioSection(QGroupBox):
    """Volume slider driving the CCCP theme's anthem playback."""

    volume_changed = Signal(int)  # 0-100, applied live so a currently-playing anthem reacts immediately

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(tr("profile_tab.audio_group"), parent)
        self._settings = settings
        self._form_labels: dict[str, QLabel] = {}
        form = QFormLayout(self)

        volume_row = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Horizontal, self)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(settings.audio_volume)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.volume_slider.sliderReleased.connect(self._on_volume_slider_released)
        volume_row.addWidget(self.volume_slider, 1)
        self.volume_value_label = QLabel(f"{settings.audio_volume}%", self)
        self.volume_value_label.setFixedWidth(40)
        volume_row.addWidget(self.volume_value_label)
        _add_row(form, self._form_labels, "profile_tab.audio_volume_label", volume_row)

        self.audio_note = QLabel(tr("profile_tab.audio_note"), self)
        self.audio_note.setWordWrap(True)
        form.addRow(self.audio_note)

    def retranslate_ui(self) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))
        self.setTitle(tr("profile_tab.audio_group"))
        self.audio_note.setText(tr("profile_tab.audio_note"))

    def write_to(self, settings: Settings) -> None:
        settings.audio_volume = self.volume_slider.value()

    def _on_volume_changed(self, value: int) -> None:
        # Applied live (in-memory + signal emit) on every tick so a
        # currently-playing anthem reacts while dragging, but the disk write
        # is deferred to slider-release/Save -- saving on every tick of a
        # drag would otherwise hammer the config file dozens of times a second.
        self.volume_value_label.setText(f"{value}%")
        self._settings.audio_volume = value
        self.volume_changed.emit(value)

    def _on_volume_slider_released(self) -> None:
        self._settings.save()


class BandwidthScheduleSection(QGroupBox):
    """A single daily reduced-speed window."""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(tr("profile_tab.schedule_group"), parent)
        self._form_labels: dict[str, QLabel] = {}
        form = QFormLayout(self)
        schedule = settings.bandwidth_schedule

        self.schedule_enabled_checkbox = QCheckBox(tr("profile_tab.schedule_enabled"), self)
        self.schedule_enabled_checkbox.setChecked(schedule.enabled)
        form.addRow(self.schedule_enabled_checkbox)

        hours_row = QHBoxLayout()
        self.schedule_start_spin = QSpinBox(self)
        self.schedule_start_spin.setRange(0, 23)
        self.schedule_start_spin.setSuffix(" h")
        self.schedule_start_spin.setValue(schedule.start_hour)
        self.schedule_from_label = QLabel(tr("profile_tab.schedule_from"), self)
        hours_row.addWidget(self.schedule_from_label)
        hours_row.addWidget(self.schedule_start_spin)
        self.schedule_end_spin = QSpinBox(self)
        self.schedule_end_spin.setRange(0, 23)
        self.schedule_end_spin.setSuffix(" h")
        self.schedule_end_spin.setValue(schedule.end_hour)
        self.schedule_to_label = QLabel(tr("profile_tab.schedule_to"), self)
        hours_row.addWidget(self.schedule_to_label)
        hours_row.addWidget(self.schedule_end_spin)
        hours_row.addStretch(1)
        _add_row(form, self._form_labels, "profile_tab.schedule_window", hours_row)

        self.schedule_download_spin = QSpinBox(self)
        self.schedule_download_spin.setRange(0, 1_000_000)
        self.schedule_download_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.schedule_download_spin.setValue(schedule.limited_download_kbps)
        _add_row(form, self._form_labels, "profile_tab.schedule_download", self.schedule_download_spin)

        self.schedule_upload_spin = QSpinBox(self)
        self.schedule_upload_spin.setRange(0, 1_000_000)
        self.schedule_upload_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.schedule_upload_spin.setValue(schedule.limited_upload_kbps)
        _add_row(form, self._form_labels, "profile_tab.schedule_upload", self.schedule_upload_spin)

        self.schedule_note = QLabel(tr("profile_tab.schedule_note"), self)
        self.schedule_note.setWordWrap(True)
        form.addRow(self.schedule_note)

    def retranslate_ui(self) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))
        self.setTitle(tr("profile_tab.schedule_group"))
        self.schedule_enabled_checkbox.setText(tr("profile_tab.schedule_enabled"))
        self.schedule_from_label.setText(tr("profile_tab.schedule_from"))
        self.schedule_to_label.setText(tr("profile_tab.schedule_to"))
        self.schedule_download_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.schedule_upload_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.schedule_note.setText(tr("profile_tab.schedule_note"))

    def write_to(self, settings: Settings) -> None:
        settings.bandwidth_schedule.enabled = self.schedule_enabled_checkbox.isChecked()
        settings.bandwidth_schedule.start_hour = self.schedule_start_spin.value()
        settings.bandwidth_schedule.end_hour = self.schedule_end_spin.value()
        settings.bandwidth_schedule.limited_download_kbps = self.schedule_download_spin.value()
        settings.bandwidth_schedule.limited_upload_kbps = self.schedule_upload_spin.value()


class SecuritySection(QGroupBox):
    """Shortcut to Windows Security's exclusions page, plus the opt-in
    post-download Defender scan toggle."""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(tr("profile_tab.security_group"), parent)
        layout = QVBoxLayout(self)
        self.defender_button = QPushButton(tr("profile_tab.defender_button"), self)
        self.defender_button.clicked.connect(self._on_open_defender_settings)
        layout.addWidget(self.defender_button)
        self.security_note = QLabel(tr("profile_tab.security_note"), self)
        self.security_note.setWordWrap(True)
        layout.addWidget(self.security_note)

        self.av_scan_checkbox = QCheckBox(tr("profile_tab.av_scan_checkbox"), self)
        self.av_scan_checkbox.setChecked(settings.scan_completed_files_with_defender)
        layout.addWidget(self.av_scan_checkbox)

    def retranslate_ui(self) -> None:
        self.setTitle(tr("profile_tab.security_group"))
        self.defender_button.setText(tr("profile_tab.defender_button"))
        self.security_note.setText(tr("profile_tab.security_note"))
        self.av_scan_checkbox.setText(tr("profile_tab.av_scan_checkbox"))

    def write_to(self, settings: Settings) -> None:
        settings.scan_completed_files_with_defender = self.av_scan_checkbox.isChecked()

    def _on_open_defender_settings(self) -> None:
        # Opens the Windows Security app to its exclusions page. The user adds
        # any exclusion themselves -- this app never writes to Defender's
        # exclusion list programmatically.
        QDesktopServices.openUrl(QUrl("windowsdefender://threatsettings"))


class DiagnosticsSection(QGroupBox):
    """Local, user-initiated way to hand over a debug log -- no state of its own."""

    def __init__(self, parent=None) -> None:
        super().__init__(tr("profile_tab.diagnostics_group"), parent)
        layout = QVBoxLayout(self)
        self.open_logs_button = QPushButton(tr("profile_tab.open_logs_button"), self)
        self.open_logs_button.clicked.connect(self._on_open_logs_folder)
        layout.addWidget(self.open_logs_button)
        self.copy_log_button = QPushButton(tr("profile_tab.copy_log_button"), self)
        self.copy_log_button.clicked.connect(self._on_copy_log)
        layout.addWidget(self.copy_log_button)
        self.diagnostics_note = QLabel(tr("profile_tab.diagnostics_note"), self)
        self.diagnostics_note.setWordWrap(True)
        layout.addWidget(self.diagnostics_note)

    def retranslate_ui(self) -> None:
        self.setTitle(tr("profile_tab.diagnostics_group"))
        self.open_logs_button.setText(tr("profile_tab.open_logs_button"))
        self.copy_log_button.setText(tr("profile_tab.copy_log_button"))
        self.diagnostics_note.setText(tr("profile_tab.diagnostics_note"))

    def write_to(self, settings: Settings) -> None:
        pass  # nothing to persist -- this section is action-only

    def _on_open_logs_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_logs_dir())))

    def _on_copy_log(self) -> None:
        log_path = get_logs_dir() / "torrent2000.log"
        try:
            content = log_path.read_text(encoding="utf-8")
        except OSError:
            QMessageBox.information(self, tr("profile_tab.no_log_title"), tr("profile_tab.no_log_message"))
            return
        QApplication.clipboard().setText(content)
        QMessageBox.information(self, tr("profile_tab.log_copied_title"), tr("profile_tab.log_copied_message"))


class ConfigImportExportSection(QGroupBox):
    """Export/import the whole Settings dataclass as JSON."""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(tr("profile_tab.config_group"), parent)
        self._settings = settings
        layout = QVBoxLayout(self)
        button_row = QHBoxLayout()
        self.export_button = QPushButton(tr("profile_tab.export_button"), self)
        self.export_button.clicked.connect(self._on_export_settings)
        button_row.addWidget(self.export_button)
        self.import_button = QPushButton(tr("profile_tab.import_button"), self)
        self.import_button.clicked.connect(self._on_import_settings)
        button_row.addWidget(self.import_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        self.export_password_note = QLabel(tr("profile_tab.export_password_note"), self)
        self.export_password_note.setWordWrap(True)
        layout.addWidget(self.export_password_note)

    def retranslate_ui(self) -> None:
        self.setTitle(tr("profile_tab.config_group"))
        self.export_button.setText(tr("profile_tab.export_button"))
        self.import_button.setText(tr("profile_tab.import_button"))
        self.export_password_note.setText(tr("profile_tab.export_password_note"))

    def write_to(self, settings: Settings) -> None:
        pass  # export/import act on disk directly, nothing to batch via Save

    def _on_export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("profile_tab.export_title"), "torrent2000_config.json", "JSON (*.json)"
        )
        if not path:
            return
        # The proxy password must never leave the machine in a plain-text
        # export -- redact it before serializing rather than after, so there
        # is no code path that can write the real value by omission.
        data = asdict(self._settings)
        if data.get("proxy"):
            data["proxy"]["password"] = ""
        try:
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.warning("Config export to %s failed: %s", path, exc)
            QMessageBox.warning(self, tr("profile_tab.export_failed_title"), tr("profile_tab.export_failed_message"))
            return
        QMessageBox.information(self, tr("profile_tab.export_success_title"), tr("profile_tab.export_success_message", path=path))

    def _on_import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("profile_tab.import_title"), "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Config import from %s failed: invalid JSON: %s", path, exc)
            QMessageBox.warning(self, tr("profile_tab.import_failed_title"), tr("profile_tab.import_failed_message_invalid"))
            return
        except OSError as exc:
            logger.warning("Config import from %s failed: %s", path, exc)
            QMessageBox.warning(self, tr("profile_tab.import_failed_title"), tr("profile_tab.import_failed_message_os"))
            return
        if not self._is_valid_settings_payload(data):
            logger.warning("Config import from %s failed: does not reconstruct into a valid Settings", path)
            QMessageBox.warning(self, tr("profile_tab.import_failed_title"), tr("profile_tab.import_failed_message_schema"))
            return
        reply = QMessageBox.question(
            self,
            tr("profile_tab.import_confirm_title"),
            tr("profile_tab.import_confirm_message"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        # Written straight to the real config file rather than trying to
        # live-patch every open widget/service -- simpler and avoids partial
        # application bugs. Applied fully on next launch.
        get_config_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        QMessageBox.information(self, tr("profile_tab.import_success_title"), tr("profile_tab.import_success_message"))

    @staticmethod
    def _is_valid_settings_payload(data: object) -> bool:
        """Confirms `data` reconstructs into a coherent Settings object,
        via the same dict-shape and sub-structure handling Settings.load()
        itself uses -- so a JSON file that merely happens to parse (e.g. a
        list, or an unrelated object) is rejected before it's ever written
        to the real config file."""
        if not isinstance(data, dict):
            return False
        data = dict(data)
        proxy_data = data.pop("proxy", {})
        schedule_data = data.pop("bandwidth_schedule", {})
        rss_feeds_data = data.pop("rss_feeds", [])
        try:
            _from_dict(Settings, data)
            _from_dict(ProxySettings, proxy_data)
            _from_dict(BandwidthSchedule, schedule_data)
            for feed in rss_feeds_data:
                _from_dict(RssFeedSubscription, feed)
        except (TypeError, AttributeError):
            return False
        return True


class NetworkPrivacySection(QGroupBox):
    """IP-masking surface: DHT/LSD restriction, proxy, network interface,
    protocol encryption."""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(tr("profile_tab.privacy_group"), parent)
        self._form_labels: dict[str, QLabel] = {}
        box_layout = QVBoxLayout(self)

        self.privacy_intro = QLabel(tr("profile_tab.privacy_intro"), self)
        self.privacy_intro.setWordWrap(True)
        box_layout.addWidget(self.privacy_intro)

        self.restrict_discovery_checkbox = QCheckBox(tr("profile_tab.restrict_discovery"), self)
        self.restrict_discovery_checkbox.setChecked(settings.restrict_discovery)
        self.restrict_discovery_checkbox.setToolTip(tr("profile_tab.restrict_discovery_tooltip"))
        box_layout.addWidget(self.restrict_discovery_checkbox)

        form = QFormLayout()
        box_layout.addLayout(form)

        self.proxy_enabled_checkbox = QCheckBox(tr("profile_tab.proxy_enabled"), self)
        self.proxy_enabled_checkbox.setChecked(settings.proxy.enabled)
        form.addRow(self.proxy_enabled_checkbox)

        self.proxy_type_combo = QComboBox(self)
        _populate_combo(self.proxy_type_combo, _proxy_type_labels(), settings.proxy.proxy_type)
        _add_row(form, self._form_labels, "profile_tab.proxy_type_label", self.proxy_type_combo)

        self.proxy_host_input = QLineEdit(settings.proxy.host, self)
        self.proxy_host_input.setPlaceholderText("proxy.example.com")
        _add_row(form, self._form_labels, "profile_tab.proxy_host_label", self.proxy_host_input)

        self.proxy_port_spin = QSpinBox(self)
        self.proxy_port_spin.setRange(0, 65535)
        self.proxy_port_spin.setValue(settings.proxy.port)
        _add_row(form, self._form_labels, "profile_tab.proxy_port_label", self.proxy_port_spin)

        self.proxy_username_input = QLineEdit(settings.proxy.username, self)
        _add_row(form, self._form_labels, "profile_tab.proxy_username_label", self.proxy_username_input)

        self.proxy_password_input = QLineEdit(settings.proxy.password, self)
        self.proxy_password_input.setEchoMode(QLineEdit.Password)
        _add_row(form, self._form_labels, "profile_tab.proxy_password_label", self.proxy_password_input)

        self.force_proxy_checkbox = QCheckBox(tr("profile_tab.force_proxy"), self)
        self.force_proxy_checkbox.setChecked(settings.proxy.force_proxy)
        self.force_proxy_checkbox.setToolTip(tr("profile_tab.force_proxy_tooltip"))
        form.addRow(self.force_proxy_checkbox)

        self.interface_combo = QComboBox(self)
        self._interfaces = _list_local_ipv4_interfaces() + _list_local_ipv6_interfaces()
        self._populate_interface_combo(settings.network_interface)
        _add_row(form, self._form_labels, "profile_tab.interface_label", self.interface_combo)

        self.encryption_combo = QComboBox(self)
        _populate_combo(self.encryption_combo, _encryption_mode_labels(), settings.encryption_mode)
        self.encryption_combo.setToolTip(tr("profile_tab.encryption_tooltip"))
        _add_row(form, self._form_labels, "profile_tab.encryption_label", self.encryption_combo)

    def _populate_interface_combo(self, current_value: str) -> None:
        self.interface_combo.blockSignals(True)
        self.interface_combo.clear()
        self.interface_combo.addItem(tr("profile_tab.interface_default"), "")
        for label, ip in self._interfaces:
            self.interface_combo.addItem(label, ip)
        idx = self.interface_combo.findData(current_value)
        self.interface_combo.setCurrentIndex(max(0, idx))
        self.interface_combo.blockSignals(False)

    def retranslate_ui(self, current_settings: Settings) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))
        self.setTitle(tr("profile_tab.privacy_group"))
        self.privacy_intro.setText(tr("profile_tab.privacy_intro"))
        self.restrict_discovery_checkbox.setText(tr("profile_tab.restrict_discovery"))
        self.restrict_discovery_checkbox.setToolTip(tr("profile_tab.restrict_discovery_tooltip"))
        self.proxy_enabled_checkbox.setText(tr("profile_tab.proxy_enabled"))
        _populate_combo(self.proxy_type_combo, _proxy_type_labels(), current_settings.proxy.proxy_type)
        self.force_proxy_checkbox.setText(tr("profile_tab.force_proxy"))
        self.force_proxy_checkbox.setToolTip(tr("profile_tab.force_proxy_tooltip"))
        self._populate_interface_combo(current_settings.network_interface)
        _populate_combo(self.encryption_combo, _encryption_mode_labels(), current_settings.encryption_mode)
        self.encryption_combo.setToolTip(tr("profile_tab.encryption_tooltip"))

    def write_to(self, settings: Settings) -> None:
        settings.restrict_discovery = self.restrict_discovery_checkbox.isChecked()
        settings.proxy.enabled = self.proxy_enabled_checkbox.isChecked()
        settings.proxy.proxy_type = self.proxy_type_combo.currentData()
        settings.proxy.host = self.proxy_host_input.text().strip()
        settings.proxy.port = self.proxy_port_spin.value()
        settings.proxy.username = self.proxy_username_input.text()
        settings.proxy.password = self.proxy_password_input.text()
        settings.proxy.force_proxy = self.force_proxy_checkbox.isChecked()
        settings.network_interface = self.interface_combo.currentData() or ""
        settings.encryption_mode = self.encryption_combo.currentData()


class WatchFolderSection(QGroupBox):
    """Auto-add any .torrent file dropped into a watched directory."""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(tr("profile_tab.watch_folder_group"), parent)
        self._form_labels: dict[str, QLabel] = {}
        form = QFormLayout(self)

        self.watch_folder_enabled_checkbox = QCheckBox(tr("profile_tab.watch_folder_enabled"), self)
        self.watch_folder_enabled_checkbox.setChecked(settings.watch_folder_enabled)
        form.addRow(self.watch_folder_enabled_checkbox)

        watch_folder_row = QHBoxLayout()
        self.watch_folder_input = QLineEdit(settings.watch_folder_path, self)
        watch_folder_row.addWidget(self.watch_folder_input)
        self.watch_folder_browse_button = QPushButton(tr("common.browse"), self)
        self.watch_folder_browse_button.clicked.connect(self._on_browse_watch_folder)
        watch_folder_row.addWidget(self.watch_folder_browse_button)
        _add_row(form, self._form_labels, "profile_tab.watch_folder_label", watch_folder_row)

        self.watch_folder_note = QLabel(tr("profile_tab.watch_folder_note"), self)
        self.watch_folder_note.setWordWrap(True)
        form.addRow(self.watch_folder_note)

    def retranslate_ui(self) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))
        self.setTitle(tr("profile_tab.watch_folder_group"))
        self.watch_folder_enabled_checkbox.setText(tr("profile_tab.watch_folder_enabled"))
        self.watch_folder_browse_button.setText(tr("common.browse"))
        self.watch_folder_note.setText(tr("profile_tab.watch_folder_note"))

    def write_to(self, settings: Settings) -> None:
        settings.watch_folder_enabled = self.watch_folder_enabled_checkbox.isChecked()
        settings.watch_folder_path = self.watch_folder_input.text().strip()

    def _on_browse_watch_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, tr("profile_tab.choose_watch_folder_title"), self.watch_folder_input.text()
        )
        if directory:
            self.watch_folder_input.setText(directory)


class DiskSpaceSection(QGroupBox):
    """Warn when free space at a download destination drops too low."""

    def __init__(self, settings: Settings, disk_space_monitor: DiskSpaceMonitor, parent=None) -> None:
        super().__init__(tr("profile_tab.disk_space_group"), parent)
        self._form_labels: dict[str, QLabel] = {}
        form = QFormLayout(self)

        self.disk_space_enabled_checkbox = QCheckBox(tr("profile_tab.disk_space_enabled"), self)
        self.disk_space_enabled_checkbox.setChecked(settings.disk_space_warning_enabled)
        form.addRow(self.disk_space_enabled_checkbox)

        self.disk_space_threshold_spin = QSpinBox(self)
        self.disk_space_threshold_spin.setRange(1, 1_000_000)
        self.disk_space_threshold_spin.setSuffix(" Mo")
        self.disk_space_threshold_spin.setValue(settings.disk_space_warning_threshold_mb)
        _add_row(form, self._form_labels, "profile_tab.disk_space_threshold_label", self.disk_space_threshold_spin)

        disk_space_monitor.low_space_warning.connect(self._on_low_space_warning)

    def retranslate_ui(self) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))
        self.setTitle(tr("profile_tab.disk_space_group"))
        self.disk_space_enabled_checkbox.setText(tr("profile_tab.disk_space_enabled"))

    def write_to(self, settings: Settings) -> None:
        settings.disk_space_warning_enabled = self.disk_space_enabled_checkbox.isChecked()
        settings.disk_space_warning_threshold_mb = self.disk_space_threshold_spin.value()

    def _on_low_space_warning(self, save_path: str, message: str) -> None:
        QMessageBox.warning(self, tr("profile_tab.low_space_title"), message)


class AutoShutdownSection(QGroupBox):
    """Shut down/hibernate once every torrent has finished downloading."""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(tr("profile_tab.shutdown_group"), parent)
        self._form_labels: dict[str, QLabel] = {}
        form = QFormLayout(self)

        self.shutdown_enabled_checkbox = QCheckBox(tr("profile_tab.shutdown_enabled"), self)
        self.shutdown_enabled_checkbox.setChecked(settings.auto_shutdown_enabled)
        form.addRow(self.shutdown_enabled_checkbox)

        self.shutdown_action_combo = QComboBox(self)
        _populate_combo(self.shutdown_action_combo, _shutdown_action_labels(), settings.auto_shutdown_action)
        _add_row(form, self._form_labels, "profile_tab.shutdown_action_label", self.shutdown_action_combo)

        self.shutdown_delay_spin = QSpinBox(self)
        self.shutdown_delay_spin.setRange(0, 3600)
        self.shutdown_delay_spin.setSuffix(" s")
        self.shutdown_delay_spin.setValue(settings.auto_shutdown_delay_seconds)
        _add_row(form, self._form_labels, "profile_tab.shutdown_delay_label", self.shutdown_delay_spin)

        self.shutdown_note = QLabel(tr("profile_tab.shutdown_note"), self)
        self.shutdown_note.setWordWrap(True)
        form.addRow(self.shutdown_note)

    def retranslate_ui(self, current_settings: Settings) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))
        self.setTitle(tr("profile_tab.shutdown_group"))
        self.shutdown_enabled_checkbox.setText(tr("profile_tab.shutdown_enabled"))
        _populate_combo(self.shutdown_action_combo, _shutdown_action_labels(), current_settings.auto_shutdown_action)
        self.shutdown_note.setText(tr("profile_tab.shutdown_note"))

    def write_to(self, settings: Settings) -> None:
        settings.auto_shutdown_enabled = self.shutdown_enabled_checkbox.isChecked()
        settings.auto_shutdown_action = self.shutdown_action_combo.currentData()
        settings.auto_shutdown_delay_seconds = self.shutdown_delay_spin.value()


class BatteryPauseSection(QGroupBox):
    """Pause active downloads while running on battery power, resume once
    external power returns (see engine/battery_pause_service.py)."""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(tr("profile_tab.battery_group"), parent)
        layout = QVBoxLayout(self)

        self.battery_pause_checkbox = QCheckBox(tr("profile_tab.battery_pause_checkbox"), self)
        self.battery_pause_checkbox.setChecked(settings.pause_on_battery_enabled)
        layout.addWidget(self.battery_pause_checkbox)

        self.battery_note = QLabel(tr("profile_tab.battery_note"), self)
        self.battery_note.setWordWrap(True)
        layout.addWidget(self.battery_note)

    def retranslate_ui(self) -> None:
        self.setTitle(tr("profile_tab.battery_group"))
        self.battery_pause_checkbox.setText(tr("profile_tab.battery_pause_checkbox"))
        self.battery_note.setText(tr("profile_tab.battery_note"))

    def write_to(self, settings: Settings) -> None:
        settings.pause_on_battery_enabled = self.battery_pause_checkbox.isChecked()


class LevelingSection(QGroupBox):
    """Current level, progress to next, and cumulative downloaded/uploaded totals."""

    def __init__(self, settings: Settings, stats_service: StatsService, parent=None) -> None:
        super().__init__(tr("profile_tab.leveling_group"), parent)
        self._settings = settings
        self._stats_service = stats_service
        layout = QVBoxLayout(self)
        self.level_label = QLabel(tr("profile_tab.level_value", level=0), self)
        layout.addWidget(self.level_label)
        self.level_progress_bar = QProgressBar(self)
        self.level_progress_bar.setRange(0, 1000)
        layout.addWidget(self.level_progress_bar)
        self.totals_label = QLabel(self)
        layout.addWidget(self.totals_label)

        stats_service.snapshot_updated.connect(self._on_snapshot_updated)
        self._on_snapshot_updated(stats_service.current_snapshot())

    def retranslate_ui(self) -> None:
        self.setTitle(tr("profile_tab.leveling_group"))
        self._on_snapshot_updated(self._stats_service.current_snapshot())

    def write_to(self, settings: Settings) -> None:
        pass  # read-only display, nothing to persist

    def _on_snapshot_updated(self, snap: StatsSnapshot) -> None:
        self.level_label.setText(tr("profile_tab.level_value", level=snap.level))
        self.level_progress_bar.setValue(int(snap.progress_to_next * 1000))
        download_factor, upload_factor = score_factors_for(self._settings.theme)
        weighted = weighted_total_bytes(snap.total_downloaded, snap.total_uploaded, download_factor, upload_factor)
        self.level_progress_bar.setFormat(f"{human_size(weighted)} / {human_size(snap.next_threshold)}")
        if self._settings.theme == MACOS_THEME_ID:
            multiplier_note = tr("profile_tab.multiplier_note_macos")
        elif self._settings.theme == CCCP_THEME_ID:
            multiplier_note = tr("profile_tab.multiplier_note_cccp")
        else:
            multiplier_note = tr("profile_tab.multiplier_note_default", percent=int(UPLOAD_LEVEL_WEIGHT * 100))
        self.totals_label.setText(
            tr(
                "profile_tab.totals_label",
                downloaded=human_size(snap.total_downloaded),
                uploaded=human_size(snap.total_uploaded),
                note=multiplier_note,
            )
        )


class HistorySection(QGroupBox):
    """Table of completed torrents (name, size, downloaded, uploaded, date)."""

    def __init__(self, history_service: HistoryService, parent=None) -> None:
        super().__init__(tr("profile_tab.history_group"), parent)
        self._history_service = history_service
        layout = QVBoxLayout(self)
        self.history_table = QTableWidget(0, 5, self)
        self.history_table.setHorizontalHeaderLabels(self._columns())
        # Deliberately NOT QHeaderView.Stretch: a Stretch column keeps total
        # header width pinned to the viewport, so resizing any OTHER column
        # silently shrinks/grows this one to compensate -- from the user's
        # side, dragging a column border elsewhere makes THIS column's
        # border move instead, while the one actually dragged snaps back
        # to where it started. A fixed initial width with plain Interactive
        # resizing (the default) makes every column resize independently.
        self.history_table.setColumnWidth(0, 220)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setMaximumHeight(160)
        layout.addWidget(self.history_table)

        button_row = QHBoxLayout()
        self.clear_history_button = QPushButton(tr("profile_tab.clear_history_button"), self)
        self.clear_history_button.clicked.connect(self._on_clear_history_clicked)
        button_row.addWidget(self.clear_history_button)
        self.export_csv_button = QPushButton(tr("profile_tab.export_csv_button"), self)
        self.export_csv_button.clicked.connect(self._on_export_csv_clicked)
        button_row.addWidget(self.export_csv_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        history_service.entry_added.connect(self.refresh)
        self.refresh()

    def _columns(self) -> list[str]:
        return [
            tr("profile_tab.history_column_name"),
            tr("profile_tab.history_column_size"),
            tr("profile_tab.history_column_downloaded"),
            tr("profile_tab.history_column_uploaded"),
            tr("profile_tab.history_column_date"),
        ]

    def retranslate_ui(self) -> None:
        self.setTitle(tr("profile_tab.history_group"))
        self.history_table.setHorizontalHeaderLabels(self._columns())
        self.clear_history_button.setText(tr("profile_tab.clear_history_button"))
        self.export_csv_button.setText(tr("profile_tab.export_csv_button"))

    def write_to(self, settings: Settings) -> None:
        pass  # read-only display, nothing to persist

    def refresh(self) -> None:
        entries = self._history_service.all_entries()
        self.history_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.history_table.setItem(row, 0, QTableWidgetItem(entry.name))
            self.history_table.setItem(row, 1, QTableWidgetItem(human_size(entry.total_size)))
            self.history_table.setItem(row, 2, QTableWidgetItem(human_size(entry.total_downloaded)))
            self.history_table.setItem(row, 3, QTableWidgetItem(human_size(entry.total_uploaded)))
            self.history_table.setItem(row, 4, QTableWidgetItem(entry.finished_at))

    def _on_export_csv_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("profile_tab.export_csv_title"), "torrent2000_historique.csv", "CSV (*.csv)"
        )
        if not path:
            return
        entries = self._history_service.all_entries()
        try:
            # Raw byte counts (not human_size() strings) -- a CSV export is
            # meant to be re-parsed by another tool, so it should carry
            # numbers, not formatted text.
            with open(path, "w", newline="", encoding="utf-8") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(self._columns())
                for entry in entries:
                    writer.writerow(
                        [entry.name, entry.total_size, entry.total_downloaded, entry.total_uploaded, entry.finished_at]
                    )
        except OSError as exc:
            logger.warning("History CSV export to %s failed: %s", path, exc)
            QMessageBox.warning(self, tr("profile_tab.csv_export_failed_title"), tr("profile_tab.csv_export_failed_message"))
            return
        QMessageBox.information(
            self, tr("profile_tab.csv_export_success_title"), tr("profile_tab.csv_export_success_message", path=path)
        )

    def _on_clear_history_clicked(self) -> None:
        # Local statistics only (not torrent data), but still destructive and
        # irreversible -- confirm before wiping it, same reasoning as any
        # other permanent-delete action.
        reply = QMessageBox.question(
            self,
            tr("profile_tab.clear_history_confirm_title"),
            tr("profile_tab.clear_history_confirm_message"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._history_service.clear()
