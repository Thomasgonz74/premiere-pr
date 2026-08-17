from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from torrent2000.config.settings import Settings
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor
from torrent2000.engine.session_manager import SessionManager
from torrent2000.i18n.translator import tr
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.service import StatsService
from torrent2000.ui.tabs.profile_sections import (
    AudioSection,
    AutoShutdownSection,
    BandwidthScheduleSection,
    BatteryPauseSection,
    ConfigImportExportSection,
    DiagnosticsSection,
    DiskSpaceSection,
    GeneralSettingsSection,
    HistorySection,
    LevelingSection,
    NetworkPrivacySection,
    SecuritySection,
    WatchFolderSection,
)
from torrent2000.ui.widgets.remote_access_section import RemoteAccessSection
from torrent2000.ui.widgets.routing_rules_section import RoutingRulesSection
from torrent2000.ui.widgets.security_center_section import SecurityCenterSection
from torrent2000.ui.widgets.settings_profiles_section import SettingsProfilesSection


class ProfileTab(QWidget):
    """Composes the seventeen settings sections defined in profile_sections.py
    and ui/widgets/*_section.py.

    Live-apply sections (theme/appearance/language in General, volume in
    Audio) expose their own signals, relayed here so MainWindow's existing
    wiring to theme_changed/language_changed/volume_changed keeps working
    unchanged. Everything else is gated behind the Save button, which asks
    every section to write its own fields into Settings.
    """

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
        self._bandwidth_scheduler = bandwidth_scheduler
        self._settings = settings

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

        self.general_section = GeneralSettingsSection(settings, session_manager, scroll_content)
        self.general_section.theme_changed.connect(self.theme_changed)
        self.general_section.language_changed.connect(self.language_changed)
        layout.addWidget(self.general_section)

        self.audio_section = AudioSection(settings, scroll_content)
        self.audio_section.volume_changed.connect(self.volume_changed)
        layout.addWidget(self.audio_section)

        self.schedule_section = BandwidthScheduleSection(settings, scroll_content)
        layout.addWidget(self.schedule_section)

        self.security_section = SecuritySection(settings, scroll_content)
        layout.addWidget(self.security_section)

        # Opens a new network surface (a local-network listening socket), so
        # it's grouped right alongside security_section rather than further
        # down with the rest of the network-facing sections.
        self.remote_access_section = RemoteAccessSection(settings, session_manager, scroll_content)
        layout.addWidget(self.remote_access_section)

        self.diagnostics_section = DiagnosticsSection(scroll_content)
        layout.addWidget(self.diagnostics_section)

        self.config_section = ConfigImportExportSection(settings, scroll_content)
        layout.addWidget(self.config_section)

        self.network_section = NetworkPrivacySection(settings, scroll_content)
        layout.addWidget(self.network_section)

        # Summarizes security_section's and network_section's own signals
        # (proxy kill switch, discovery restriction, encryption, interface,
        # danger-scan results), so it's placed right after both.
        self.security_center_section = SecurityCenterSection(settings, session_manager, scroll_content)
        layout.addWidget(self.security_center_section)

        # Bundles/reapplies proxy, encryption, notifications, rate-limit, and
        # discovery settings together -- the same fields network_section (and
        # SecurityCenterSection above) just showed, so it reads naturally here.
        self.settings_profiles_section = SettingsProfilesSection(settings, session_manager, scroll_content)
        layout.addWidget(self.settings_profiles_section)

        # Also toggles an automatic-destination behavior (name/tracker-based
        # folder routing), so it's grouped right next to
        # settings_profiles_section above.
        self.routing_rules_section = RoutingRulesSection(settings, session_manager, scroll_content)
        layout.addWidget(self.routing_rules_section)

        self.watch_folder_section = WatchFolderSection(settings, scroll_content)
        layout.addWidget(self.watch_folder_section)

        self.disk_space_section = DiskSpaceSection(settings, disk_space_monitor, scroll_content)
        layout.addWidget(self.disk_space_section)

        self.shutdown_section = AutoShutdownSection(settings, scroll_content)
        layout.addWidget(self.shutdown_section)

        self.battery_section = BatteryPauseSection(settings, scroll_content)
        layout.addWidget(self.battery_section)

        self.leveling_section = LevelingSection(settings, stats_service, scroll_content)
        layout.addWidget(self.leveling_section)

        self.history_section = HistorySection(history_service, scroll_content)
        layout.addWidget(self.history_section)

        layout.addStretch(1)

        self._sections = [
            self.general_section,
            self.audio_section,
            self.schedule_section,
            self.security_section,
            self.remote_access_section,
            self.diagnostics_section,
            self.config_section,
            self.network_section,
            self.security_center_section,
            self.settings_profiles_section,
            self.routing_rules_section,
            self.watch_folder_section,
            self.disk_space_section,
            self.shutdown_section,
            self.battery_section,
            self.leveling_section,
            self.history_section,
        ]

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

    def retranslate_ui(self) -> None:
        self.general_section.retranslate_ui()
        self.audio_section.retranslate_ui()
        self.schedule_section.retranslate_ui()
        self.security_section.retranslate_ui()
        self.remote_access_section.retranslate_ui()
        self.diagnostics_section.retranslate_ui()
        self.config_section.retranslate_ui()
        self.network_section.retranslate_ui(self._settings)
        self.security_center_section.retranslate_ui()
        self.settings_profiles_section.retranslate_ui()
        self.routing_rules_section.retranslate_ui()
        self.watch_folder_section.retranslate_ui()
        self.disk_space_section.retranslate_ui()
        self.shutdown_section.retranslate_ui(self._settings)
        self.battery_section.retranslate_ui()
        self.leveling_section.retranslate_ui()
        self.history_section.retranslate_ui()
        self.save_button.setText(tr("profile_tab.save_button"))

    def _on_save_clicked(self) -> None:
        for section in self._sections:
            section.write_to(self._settings)
        self._settings.save()
        self._session_manager.set_rate_limits(
            self._settings.download_rate_limit_kbps, self._settings.upload_rate_limit_kbps
        )
        self._session_manager.set_restrict_discovery(self._settings.restrict_discovery)
        self._session_manager.set_proxy(self._settings)
        self._session_manager.set_network_interface(self._settings.network_interface)
        self._session_manager.set_encryption_mode(self._settings.encryption_mode)
        self._session_manager.set_max_active_downloads(self._settings.max_active_downloads)
        self._bandwidth_scheduler.settings_changed()
        # Watch folder / disk space warning / auto-shutdown are read straight
        # off self._settings by their respective services on their next timer
        # tick -- no live-apply call is needed for those.
