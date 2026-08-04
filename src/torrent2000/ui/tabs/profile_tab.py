import json
from dataclasses import asdict
from pathlib import Path

import psutil
from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrent2000.config.paths import get_config_path
from torrent2000.config.settings import Settings
from torrent2000.engine import startup_registration
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
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

# Shown once, right when the user switches TO one of these joke themes, so
# the rule changes they're about to hit aren't a silent surprise.
_THEME_SWITCH_NOTICE_KEYS = {
    MACOS_THEME_ID: ("cccp.macos_notice_title", "cccp.macos_notice_message"),
    CCCP_THEME_ID: ("cccp.notice_title", "cccp.notice_message"),
}


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


class ProfileTab(QWidget):
    theme_changed = Signal(str, str)  # theme_id, appearance_mode
    language_changed = Signal(str)  # language code
    volume_changed = Signal(int)  # 0-100, applied live so a currently-playing anthem reacts immediately

    def __init__(
        self,
        session_manager: SessionManager,
        stats_service: StatsService,
        bandwidth_scheduler: BandwidthScheduler,
        history_service: HistoryService,
        settings: Settings,
        disk_space_monitor: DiskSpaceMonitor,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._stats_service = stats_service
        self._bandwidth_scheduler = bandwidth_scheduler
        self._settings = settings
        self._disk_space_monitor = disk_space_monitor
        # Every QLabel used as a QFormLayout row caption is tracked here
        # (key -> label) so retranslate_ui() can re-apply tr() to all of
        # them without needing a named attribute per row.
        self._form_labels: dict[str, QLabel] = {}

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # This tab accumulates a lot of settings sections -- without a
        # scroll area, the combined content's minimum height bubbles up
        # through the tab widget to the frameless top-level window, forcing
        # it to be at least that tall (and preventing shrinking below it,
        # even past what a screen can show). A scroll area absorbs that
        # instead, so the window stays freely resizable.
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)

        self.general_box = QGroupBox(tr("profile_tab.general_group"), scroll_content)
        general_form = QFormLayout(self.general_box)
        self._general_form = general_form

        dest_row = QHBoxLayout()
        self.dest_input = QLineEdit(settings.default_download_dir, self.general_box)
        dest_row.addWidget(self.dest_input)
        dest_browse = QPushButton(tr("common.browse"), self.general_box)
        dest_browse.clicked.connect(self._on_browse_dest)
        self.dest_browse_button = dest_browse
        dest_row.addWidget(dest_browse)
        self._add_row(general_form, "profile_tab.default_download_dir", dest_row)

        self.download_limit_spin = QSpinBox(self.general_box)
        self.download_limit_spin.setRange(0, 1_000_000)
        self.download_limit_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.download_limit_spin.setValue(settings.download_rate_limit_kbps)
        self._add_row(general_form, "profile_tab.download_limit", self.download_limit_spin)

        self.upload_limit_spin = QSpinBox(self.general_box)
        self.upload_limit_spin.setRange(0, 1_000_000)
        self.upload_limit_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.upload_limit_spin.setValue(settings.upload_rate_limit_kbps)
        self._add_row(general_form, "profile_tab.upload_limit", self.upload_limit_spin)

        self.danger_threshold_spin = QSpinBox(self.general_box)
        self.danger_threshold_spin.setRange(0, 100)
        self.danger_threshold_spin.setValue(settings.danger_auto_exclude_threshold)
        self._add_row(general_form, "profile_tab.danger_threshold", self.danger_threshold_spin)

        self.theme_combo = QComboBox(self.general_box)
        for label, theme_id in THEME_LABELS:
            self.theme_combo.addItem(label, theme_id)
        idx = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(0, idx))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self._add_row(general_form, "profile_tab.theme_label", self.theme_combo)

        self.appearance_combo = QComboBox(self.general_box)
        self._populate_combo(self.appearance_combo, appearance_mode_labels(), settings.appearance_mode)
        self.appearance_combo.currentIndexChanged.connect(self._on_appearance_changed)
        self._add_row(general_form, "profile_tab.appearance_mode_label", self.appearance_combo)

        self.language_combo = QComboBox(self.general_box)
        # Each language's own name is always shown in that language itself
        # (autonym), never translated -- "Français"/"English"/"Русский"
        # stay the same no matter which language is currently active, the
        # same convention every OS/app language picker already uses.
        self._populate_combo(self.language_combo, LANGUAGE_LABELS, settings.language)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._add_row(general_form, "profile_tab.language_label", self.language_combo)

        self.notifications_checkbox = QCheckBox(tr("profile_tab.notifications_checkbox"), self.general_box)
        self.notifications_checkbox.setChecked(settings.notifications_enabled)
        general_form.addRow(self.notifications_checkbox)

        self.launch_at_startup_checkbox = QCheckBox(tr("profile_tab.launch_at_startup_checkbox"), self.general_box)
        # Reflects the real HKCU Run key rather than the possibly-stale saved
        # setting -- if the user (or a reinstall) removed it by hand, this
        # should show unchecked rather than lying about it.
        self.launch_at_startup_checkbox.setChecked(startup_registration.is_launch_at_startup_enabled())
        general_form.addRow(self.launch_at_startup_checkbox)

        layout.addWidget(self.general_box)

        self.audio_box = QGroupBox(tr("profile_tab.audio_group"), self)
        audio_form = QFormLayout(self.audio_box)
        self._audio_form = audio_form

        volume_row = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Horizontal, self.audio_box)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(settings.audio_volume)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.volume_slider.sliderReleased.connect(self._on_volume_slider_released)
        volume_row.addWidget(self.volume_slider, 1)
        self.volume_value_label = QLabel(f"{settings.audio_volume}%", self.audio_box)
        self.volume_value_label.setFixedWidth(40)
        volume_row.addWidget(self.volume_value_label)
        self._add_row(audio_form, "profile_tab.audio_volume_label", volume_row)

        self.audio_note = QLabel(tr("profile_tab.audio_note"), self.audio_box)
        self.audio_note.setWordWrap(True)
        audio_form.addRow(self.audio_note)

        layout.addWidget(self.audio_box)

        self.schedule_box = QGroupBox(tr("profile_tab.schedule_group"), self)
        schedule_form = QFormLayout(self.schedule_box)
        self._schedule_form = schedule_form

        schedule = settings.bandwidth_schedule
        self.schedule_enabled_checkbox = QCheckBox(tr("profile_tab.schedule_enabled"), self.schedule_box)
        self.schedule_enabled_checkbox.setChecked(schedule.enabled)
        schedule_form.addRow(self.schedule_enabled_checkbox)

        hours_row = QHBoxLayout()
        self.schedule_start_spin = QSpinBox(self.schedule_box)
        self.schedule_start_spin.setRange(0, 23)
        self.schedule_start_spin.setSuffix(" h")
        self.schedule_start_spin.setValue(schedule.start_hour)
        self.schedule_from_label = QLabel(tr("profile_tab.schedule_from"), self.schedule_box)
        hours_row.addWidget(self.schedule_from_label)
        hours_row.addWidget(self.schedule_start_spin)
        self.schedule_end_spin = QSpinBox(self.schedule_box)
        self.schedule_end_spin.setRange(0, 23)
        self.schedule_end_spin.setSuffix(" h")
        self.schedule_end_spin.setValue(schedule.end_hour)
        self.schedule_to_label = QLabel(tr("profile_tab.schedule_to"), self.schedule_box)
        hours_row.addWidget(self.schedule_to_label)
        hours_row.addWidget(self.schedule_end_spin)
        hours_row.addStretch(1)
        self._add_row(schedule_form, "profile_tab.schedule_window", hours_row)

        self.schedule_download_spin = QSpinBox(self.schedule_box)
        self.schedule_download_spin.setRange(0, 1_000_000)
        self.schedule_download_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.schedule_download_spin.setValue(schedule.limited_download_kbps)
        self._add_row(schedule_form, "profile_tab.schedule_download", self.schedule_download_spin)

        self.schedule_upload_spin = QSpinBox(self.schedule_box)
        self.schedule_upload_spin.setRange(0, 1_000_000)
        self.schedule_upload_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.schedule_upload_spin.setValue(schedule.limited_upload_kbps)
        self._add_row(schedule_form, "profile_tab.schedule_upload", self.schedule_upload_spin)

        self.schedule_note = QLabel(tr("profile_tab.schedule_note"), self.schedule_box)
        self.schedule_note.setWordWrap(True)
        schedule_form.addRow(self.schedule_note)

        layout.addWidget(self.schedule_box)

        self.security_box = QGroupBox(tr("profile_tab.security_group"), self)
        security_layout = QVBoxLayout(self.security_box)
        self.defender_button = QPushButton(tr("profile_tab.defender_button"), self.security_box)
        self.defender_button.clicked.connect(self._on_open_defender_settings)
        security_layout.addWidget(self.defender_button)
        self.security_note = QLabel(tr("profile_tab.security_note"), self.security_box)
        self.security_note.setWordWrap(True)
        security_layout.addWidget(self.security_note)
        layout.addWidget(self.security_box)

        self.config_box = QGroupBox(tr("profile_tab.config_group"), self)
        config_layout = QHBoxLayout(self.config_box)
        self.export_button = QPushButton(tr("profile_tab.export_button"), self.config_box)
        self.export_button.clicked.connect(self._on_export_settings)
        config_layout.addWidget(self.export_button)
        self.import_button = QPushButton(tr("profile_tab.import_button"), self.config_box)
        self.import_button.clicked.connect(self._on_import_settings)
        config_layout.addWidget(self.import_button)
        config_layout.addStretch(1)
        layout.addWidget(self.config_box)

        self.network_box = QGroupBox(tr("profile_tab.privacy_group"), self)
        network_box_layout = QVBoxLayout(self.network_box)

        self.privacy_intro = QLabel(tr("profile_tab.privacy_intro"), self.network_box)
        self.privacy_intro.setWordWrap(True)
        network_box_layout.addWidget(self.privacy_intro)

        self.restrict_discovery_checkbox = QCheckBox(tr("profile_tab.restrict_discovery"), self.network_box)
        self.restrict_discovery_checkbox.setChecked(settings.restrict_discovery)
        self.restrict_discovery_checkbox.setToolTip(tr("profile_tab.restrict_discovery_tooltip"))
        network_box_layout.addWidget(self.restrict_discovery_checkbox)

        network_form = QFormLayout()
        self._network_form = network_form
        network_box_layout.addLayout(network_form)

        self.proxy_enabled_checkbox = QCheckBox(tr("profile_tab.proxy_enabled"), self.network_box)
        self.proxy_enabled_checkbox.setChecked(settings.proxy.enabled)
        network_form.addRow(self.proxy_enabled_checkbox)

        self.proxy_type_combo = QComboBox(self.network_box)
        self._populate_combo(self.proxy_type_combo, _proxy_type_labels(), settings.proxy.proxy_type)
        self._add_row(network_form, "profile_tab.proxy_type_label", self.proxy_type_combo)

        self.proxy_host_input = QLineEdit(settings.proxy.host, self.network_box)
        self.proxy_host_input.setPlaceholderText("proxy.example.com")
        self._add_row(network_form, "profile_tab.proxy_host_label", self.proxy_host_input)

        self.proxy_port_spin = QSpinBox(self.network_box)
        self.proxy_port_spin.setRange(0, 65535)
        self.proxy_port_spin.setValue(settings.proxy.port)
        self._add_row(network_form, "profile_tab.proxy_port_label", self.proxy_port_spin)

        self.proxy_username_input = QLineEdit(settings.proxy.username, self.network_box)
        self._add_row(network_form, "profile_tab.proxy_username_label", self.proxy_username_input)

        self.proxy_password_input = QLineEdit(settings.proxy.password, self.network_box)
        self.proxy_password_input.setEchoMode(QLineEdit.Password)
        self._add_row(network_form, "profile_tab.proxy_password_label", self.proxy_password_input)

        self.force_proxy_checkbox = QCheckBox(tr("profile_tab.force_proxy"), self.network_box)
        self.force_proxy_checkbox.setChecked(settings.proxy.force_proxy)
        self.force_proxy_checkbox.setToolTip(tr("profile_tab.force_proxy_tooltip"))
        network_form.addRow(self.force_proxy_checkbox)

        self.interface_combo = QComboBox(self.network_box)
        self._interfaces = _list_local_ipv4_interfaces()
        self._populate_interface_combo(settings.network_interface)
        self._add_row(network_form, "profile_tab.interface_label", self.interface_combo)

        self.encryption_combo = QComboBox(self.network_box)
        self._populate_combo(self.encryption_combo, _encryption_mode_labels(), settings.encryption_mode)
        self.encryption_combo.setToolTip(tr("profile_tab.encryption_tooltip"))
        self._add_row(network_form, "profile_tab.encryption_label", self.encryption_combo)

        layout.addWidget(self.network_box)

        self.watch_folder_box = QGroupBox(tr("profile_tab.watch_folder_group"), self)
        watch_folder_form = QFormLayout(self.watch_folder_box)
        self._watch_folder_form = watch_folder_form

        self.watch_folder_enabled_checkbox = QCheckBox(tr("profile_tab.watch_folder_enabled"), self.watch_folder_box)
        self.watch_folder_enabled_checkbox.setChecked(settings.watch_folder_enabled)
        watch_folder_form.addRow(self.watch_folder_enabled_checkbox)

        watch_folder_row = QHBoxLayout()
        self.watch_folder_input = QLineEdit(settings.watch_folder_path, self.watch_folder_box)
        watch_folder_row.addWidget(self.watch_folder_input)
        self.watch_folder_browse_button = QPushButton(tr("common.browse"), self.watch_folder_box)
        self.watch_folder_browse_button.clicked.connect(self._on_browse_watch_folder)
        watch_folder_row.addWidget(self.watch_folder_browse_button)
        self._add_row(watch_folder_form, "profile_tab.watch_folder_label", watch_folder_row)

        self.watch_folder_note = QLabel(tr("profile_tab.watch_folder_note"), self.watch_folder_box)
        self.watch_folder_note.setWordWrap(True)
        watch_folder_form.addRow(self.watch_folder_note)

        layout.addWidget(self.watch_folder_box)

        self.disk_space_box = QGroupBox(tr("profile_tab.disk_space_group"), self)
        disk_space_form = QFormLayout(self.disk_space_box)
        self._disk_space_form = disk_space_form

        self.disk_space_enabled_checkbox = QCheckBox(tr("profile_tab.disk_space_enabled"), self.disk_space_box)
        self.disk_space_enabled_checkbox.setChecked(settings.disk_space_warning_enabled)
        disk_space_form.addRow(self.disk_space_enabled_checkbox)

        self.disk_space_threshold_spin = QSpinBox(self.disk_space_box)
        self.disk_space_threshold_spin.setRange(1, 1_000_000)
        self.disk_space_threshold_spin.setSuffix(" Mo")
        self.disk_space_threshold_spin.setValue(settings.disk_space_warning_threshold_mb)
        self._add_row(disk_space_form, "profile_tab.disk_space_threshold_label", self.disk_space_threshold_spin)

        layout.addWidget(self.disk_space_box)

        self.shutdown_box = QGroupBox(tr("profile_tab.shutdown_group"), self)
        shutdown_form = QFormLayout(self.shutdown_box)
        self._shutdown_form = shutdown_form

        self.shutdown_enabled_checkbox = QCheckBox(tr("profile_tab.shutdown_enabled"), self.shutdown_box)
        self.shutdown_enabled_checkbox.setChecked(settings.auto_shutdown_enabled)
        shutdown_form.addRow(self.shutdown_enabled_checkbox)

        self.shutdown_action_combo = QComboBox(self.shutdown_box)
        self._populate_combo(self.shutdown_action_combo, _shutdown_action_labels(), settings.auto_shutdown_action)
        self._add_row(shutdown_form, "profile_tab.shutdown_action_label", self.shutdown_action_combo)

        self.shutdown_delay_spin = QSpinBox(self.shutdown_box)
        self.shutdown_delay_spin.setRange(0, 3600)
        self.shutdown_delay_spin.setSuffix(" s")
        self.shutdown_delay_spin.setValue(settings.auto_shutdown_delay_seconds)
        self._add_row(shutdown_form, "profile_tab.shutdown_delay_label", self.shutdown_delay_spin)

        self.shutdown_note = QLabel(tr("profile_tab.shutdown_note"), self.shutdown_box)
        self.shutdown_note.setWordWrap(True)
        shutdown_form.addRow(self.shutdown_note)

        layout.addWidget(self.shutdown_box)

        self.leveling_box = QGroupBox(tr("profile_tab.leveling_group"), self)
        leveling_layout = QVBoxLayout(self.leveling_box)
        self.level_label = QLabel(tr("profile_tab.level_value", level=0), self.leveling_box)
        leveling_layout.addWidget(self.level_label)
        self.level_progress_bar = QProgressBar(self.leveling_box)
        self.level_progress_bar.setRange(0, 1000)
        leveling_layout.addWidget(self.level_progress_bar)
        self.totals_label = QLabel(self.leveling_box)
        leveling_layout.addWidget(self.totals_label)
        layout.addWidget(self.leveling_box)

        stats_service.snapshot_updated.connect(self._on_snapshot_updated)
        self._on_snapshot_updated(stats_service.current_snapshot())

        self.history_box = QGroupBox(tr("profile_tab.history_group"), self)
        history_layout = QVBoxLayout(self.history_box)
        self.history_table = QTableWidget(0, 5, self.history_box)
        self.history_table.setHorizontalHeaderLabels(self._history_columns())
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setMaximumHeight(160)
        history_layout.addWidget(self.history_table)
        layout.addWidget(self.history_box)

        self._history_service = history_service
        history_service.entry_added.connect(self._refresh_history)
        self._refresh_history()

        layout.addStretch(1)

        scroll_area.setWidget(scroll_content)
        outer_layout.addWidget(scroll_area, 1)

        # Kept outside the scroll area, pinned at the bottom, so it's always
        # reachable without having to scroll all the way down first.
        save_row = QHBoxLayout()
        save_row.setContentsMargins(8, 6, 8, 8)
        save_row.addStretch(1)
        self.save_button = QPushButton(tr("profile_tab.save_button"), self)
        self.save_button.clicked.connect(self._on_save_clicked)
        save_row.addWidget(self.save_button)
        outer_layout.addLayout(save_row)

        self._disk_space_monitor.low_space_warning.connect(self._on_low_space_warning)

    # -------------------------------------------------------------- helpers

    def _add_row(self, form: QFormLayout, key: str, field) -> None:
        label = QLabel(tr(key), form.parentWidget())
        self._form_labels[key] = label
        form.addRow(label, field)

    def _populate_combo(self, combo: QComboBox, labels: list[tuple[str, str]], current_value: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        for label, value in labels:
            combo.addItem(label, value)
        idx = combo.findData(current_value)
        combo.setCurrentIndex(max(0, idx))
        combo.blockSignals(False)

    def _populate_interface_combo(self, current_value: str) -> None:
        self.interface_combo.blockSignals(True)
        self.interface_combo.clear()
        self.interface_combo.addItem(tr("profile_tab.interface_default"), "")
        for label, ip in self._interfaces:
            self.interface_combo.addItem(label, ip)
        idx = self.interface_combo.findData(current_value)
        self.interface_combo.setCurrentIndex(max(0, idx))
        self.interface_combo.blockSignals(False)

    def _history_columns(self) -> list[str]:
        return [
            tr("profile_tab.history_column_name"),
            tr("profile_tab.history_column_size"),
            tr("profile_tab.history_column_downloaded"),
            tr("profile_tab.history_column_uploaded"),
            tr("profile_tab.history_column_date"),
        ]

    # ----------------------------------------------------------- retranslate

    def retranslate_ui(self) -> None:
        for key, label in self._form_labels.items():
            label.setText(tr(key))

        self.general_box.setTitle(tr("profile_tab.general_group"))
        self.dest_browse_button.setText(tr("common.browse"))
        self.download_limit_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.upload_limit_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self._populate_combo(self.appearance_combo, appearance_mode_labels(), self._settings.appearance_mode)
        self.notifications_checkbox.setText(tr("profile_tab.notifications_checkbox"))
        self.launch_at_startup_checkbox.setText(tr("profile_tab.launch_at_startup_checkbox"))

        self.audio_box.setTitle(tr("profile_tab.audio_group"))
        self.audio_note.setText(tr("profile_tab.audio_note"))

        self.schedule_box.setTitle(tr("profile_tab.schedule_group"))
        self.schedule_enabled_checkbox.setText(tr("profile_tab.schedule_enabled"))
        self.schedule_from_label.setText(tr("profile_tab.schedule_from"))
        self.schedule_to_label.setText(tr("profile_tab.schedule_to"))
        self.schedule_download_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.schedule_upload_spin.setSuffix(tr("common.kbps_unlimited_suffix"))
        self.schedule_note.setText(tr("profile_tab.schedule_note"))

        self.security_box.setTitle(tr("profile_tab.security_group"))
        self.defender_button.setText(tr("profile_tab.defender_button"))
        self.security_note.setText(tr("profile_tab.security_note"))

        self.config_box.setTitle(tr("profile_tab.config_group"))
        self.export_button.setText(tr("profile_tab.export_button"))
        self.import_button.setText(tr("profile_tab.import_button"))

        self.network_box.setTitle(tr("profile_tab.privacy_group"))
        self.privacy_intro.setText(tr("profile_tab.privacy_intro"))
        self.restrict_discovery_checkbox.setText(tr("profile_tab.restrict_discovery"))
        self.restrict_discovery_checkbox.setToolTip(tr("profile_tab.restrict_discovery_tooltip"))
        self.proxy_enabled_checkbox.setText(tr("profile_tab.proxy_enabled"))
        self._populate_combo(self.proxy_type_combo, _proxy_type_labels(), self._settings.proxy.proxy_type)
        self.force_proxy_checkbox.setText(tr("profile_tab.force_proxy"))
        self.force_proxy_checkbox.setToolTip(tr("profile_tab.force_proxy_tooltip"))
        self._populate_interface_combo(self._settings.network_interface)
        self._populate_combo(self.encryption_combo, _encryption_mode_labels(), self._settings.encryption_mode)
        self.encryption_combo.setToolTip(tr("profile_tab.encryption_tooltip"))

        self.watch_folder_box.setTitle(tr("profile_tab.watch_folder_group"))
        self.watch_folder_enabled_checkbox.setText(tr("profile_tab.watch_folder_enabled"))
        self.watch_folder_browse_button.setText(tr("common.browse"))
        self.watch_folder_note.setText(tr("profile_tab.watch_folder_note"))

        self.disk_space_box.setTitle(tr("profile_tab.disk_space_group"))
        self.disk_space_enabled_checkbox.setText(tr("profile_tab.disk_space_enabled"))

        self.shutdown_box.setTitle(tr("profile_tab.shutdown_group"))
        self.shutdown_enabled_checkbox.setText(tr("profile_tab.shutdown_enabled"))
        self._populate_combo(self.shutdown_action_combo, _shutdown_action_labels(), self._settings.auto_shutdown_action)
        self.shutdown_note.setText(tr("profile_tab.shutdown_note"))

        self.leveling_box.setTitle(tr("profile_tab.leveling_group"))
        self._on_snapshot_updated(self._stats_service.current_snapshot())

        self.history_box.setTitle(tr("profile_tab.history_group"))
        self.history_table.setHorizontalHeaderLabels(self._history_columns())

        self.save_button.setText(tr("profile_tab.save_button"))

    def _on_browse_dest(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("profile_tab.choose_dest_dir_title"), self.dest_input.text())
        if directory:
            self.dest_input.setText(directory)

    def _on_browse_watch_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, tr("profile_tab.choose_watch_folder_title"), self.watch_folder_input.text()
        )
        if directory:
            self.watch_folder_input.setText(directory)

    def _on_low_space_warning(self, save_path: str, message: str) -> None:
        QMessageBox.warning(self, tr("profile_tab.low_space_title"), message)

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

    def _on_export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("profile_tab.export_title"), "torrent2000_config.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(asdict(self._settings), indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, tr("profile_tab.export_failed_title"), str(exc))
            return
        QMessageBox.information(self, tr("profile_tab.export_success_title"), tr("profile_tab.export_success_message", path=path))

    def _on_import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("profile_tab.import_title"), "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, tr("profile_tab.import_failed_title"), str(exc))
            return
        # Written straight to the real config file rather than trying to
        # live-patch every open widget/service -- simpler and avoids partial
        # application bugs. Applied fully on next launch.
        get_config_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        QMessageBox.information(self, tr("profile_tab.import_success_title"), tr("profile_tab.import_success_message"))

    def _on_open_defender_settings(self) -> None:
        # Opens the Windows Security app to its exclusions page. The user adds
        # any exclusion themselves -- this app never writes to Defender's
        # exclusion list programmatically.
        QDesktopServices.openUrl(QUrl("windowsdefender://threatsettings"))

    def _on_save_clicked(self) -> None:
        self._settings.default_download_dir = self.dest_input.text().strip() or self._settings.default_download_dir
        self._settings.download_rate_limit_kbps = self.download_limit_spin.value()
        self._settings.upload_rate_limit_kbps = self.upload_limit_spin.value()
        self._settings.danger_auto_exclude_threshold = self.danger_threshold_spin.value()
        self._settings.notifications_enabled = self.notifications_checkbox.isChecked()
        self._settings.audio_volume = self.volume_slider.value()
        self._settings.launch_at_startup = self.launch_at_startup_checkbox.isChecked()
        startup_registration.set_launch_at_startup(self._settings.launch_at_startup)

        self._settings.bandwidth_schedule.enabled = self.schedule_enabled_checkbox.isChecked()
        self._settings.bandwidth_schedule.start_hour = self.schedule_start_spin.value()
        self._settings.bandwidth_schedule.end_hour = self.schedule_end_spin.value()
        self._settings.bandwidth_schedule.limited_download_kbps = self.schedule_download_spin.value()
        self._settings.bandwidth_schedule.limited_upload_kbps = self.schedule_upload_spin.value()

        self._settings.restrict_discovery = self.restrict_discovery_checkbox.isChecked()

        self._settings.proxy.enabled = self.proxy_enabled_checkbox.isChecked()
        self._settings.proxy.proxy_type = self.proxy_type_combo.currentData()
        self._settings.proxy.host = self.proxy_host_input.text().strip()
        self._settings.proxy.port = self.proxy_port_spin.value()
        self._settings.proxy.username = self.proxy_username_input.text()
        self._settings.proxy.password = self.proxy_password_input.text()
        self._settings.proxy.force_proxy = self.force_proxy_checkbox.isChecked()
        self._settings.network_interface = self.interface_combo.currentData() or ""
        self._settings.encryption_mode = self.encryption_combo.currentData()

        self._settings.watch_folder_enabled = self.watch_folder_enabled_checkbox.isChecked()
        self._settings.watch_folder_path = self.watch_folder_input.text().strip()

        self._settings.disk_space_warning_enabled = self.disk_space_enabled_checkbox.isChecked()
        self._settings.disk_space_warning_threshold_mb = self.disk_space_threshold_spin.value()

        self._settings.auto_shutdown_enabled = self.shutdown_enabled_checkbox.isChecked()
        self._settings.auto_shutdown_action = self.shutdown_action_combo.currentData()
        self._settings.auto_shutdown_delay_seconds = self.shutdown_delay_spin.value()

        self._settings.save()
        self._session_manager.set_rate_limits(
            self._settings.download_rate_limit_kbps, self._settings.upload_rate_limit_kbps
        )
        self._session_manager.set_restrict_discovery(self._settings.restrict_discovery)
        self._session_manager.set_proxy(self._settings)
        self._session_manager.set_network_interface(self._settings.network_interface)
        self._session_manager.set_encryption_mode(self._settings.encryption_mode)
        self._bandwidth_scheduler.settings_changed()
        # Watch folder / disk space warning / auto-shutdown are read straight
        # off self._settings by their respective services on their next timer
        # tick -- no live-apply call is needed for those.

    def _refresh_history(self) -> None:
        entries = self._history_service.all_entries()
        self.history_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.history_table.setItem(row, 0, QTableWidgetItem(entry.name))
            self.history_table.setItem(row, 1, QTableWidgetItem(human_size(entry.total_size)))
            self.history_table.setItem(row, 2, QTableWidgetItem(human_size(entry.total_downloaded)))
            self.history_table.setItem(row, 3, QTableWidgetItem(human_size(entry.total_uploaded)))
            self.history_table.setItem(row, 4, QTableWidgetItem(entry.finished_at))

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
