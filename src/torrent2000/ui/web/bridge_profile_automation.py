"""QWebChannel bridge backing the Profile tab's "Automation" group --
bandwidth schedule, watch folder, disk-space warning, auto-shutdown,
pause-on-battery, and provenance manifest. Mirrors BandwidthScheduleSection/
WatchFolderSection/DiskSpaceSection/AutoShutdownSection/BatteryPauseSection in
profile_sections.py exactly: same fields, same save-on-click batching, same
bandwidth_scheduler.settings_changed() live-apply call after saving the
schedule (see BandwidthScheduler.settings_changed's docstring -- without it
a currently-active window keeps running the old limits until the next 30s
timer tick).
"""

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.config.settings import Settings
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.engine.decision_journal import DecisionJournalService
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor


class ProfileAutomationBridge(QObject):
    lowSpaceWarning = Signal(str, str)  # save_path, message

    def __init__(
        self,
        settings: Settings,
        bandwidth_scheduler: BandwidthScheduler,
        disk_space_monitor: DiskSpaceMonitor,
        decision_journal_service: DecisionJournalService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._bandwidth_scheduler = bandwidth_scheduler
        self._disk_space_monitor = disk_space_monitor
        self._decision_journal_service = decision_journal_service
        disk_space_monitor.low_space_warning.connect(self.lowSpaceWarning.emit)

    @Slot(result="QVariantMap")
    def getSettings(self) -> dict:
        s = self._settings
        schedule = s.bandwidth_schedule
        return {
            "scheduleEnabled": schedule.enabled,
            "scheduleStartHour": schedule.start_hour,
            "scheduleEndHour": schedule.end_hour,
            "scheduleDownloadKbps": schedule.limited_download_kbps,
            "scheduleUploadKbps": schedule.limited_upload_kbps,
            "watchFolderEnabled": s.watch_folder_enabled,
            "watchFolderPath": s.watch_folder_path,
            "diskSpaceEnabled": s.disk_space_warning_enabled,
            "diskSpaceThresholdMb": s.disk_space_warning_threshold_mb,
            "shutdownEnabled": s.auto_shutdown_enabled,
            "shutdownAction": s.auto_shutdown_action,
            "shutdownDelaySeconds": s.auto_shutdown_delay_seconds,
            "batteryPauseEnabled": s.pause_on_battery_enabled,
            "provenanceManifestEnabled": s.provenance_manifest_enabled,
            "memoryGovernorEnabled": s.memory_governor_enabled,
            "memoryGovernorThresholdPercent": s.memory_governor_threshold_percent,
            "idleBandwidthReductionEnabled": s.idle_bandwidth_reduction_enabled,
            "idleBandwidthReductionMinutes": s.idle_bandwidth_reduction_minutes,
            "knownDiskEnabled": s.known_disk_automation_enabled,
            "peerReputationEnabled": s.peer_reputation_enabled,
            "lanPeerCacheEnabled": s.lan_peer_cache_enabled,
        }

    @Slot("QVariantMap", result="QVariantMap")
    def saveSettings(self, values: dict) -> dict:
        s = self._settings
        schedule = s.bandwidth_schedule
        schedule.enabled = bool(values.get("scheduleEnabled", schedule.enabled))
        schedule.start_hour = int(values.get("scheduleStartHour", schedule.start_hour))
        schedule.end_hour = int(values.get("scheduleEndHour", schedule.end_hour))
        schedule.limited_download_kbps = int(values.get("scheduleDownloadKbps", schedule.limited_download_kbps))
        schedule.limited_upload_kbps = int(values.get("scheduleUploadKbps", schedule.limited_upload_kbps))

        s.watch_folder_enabled = bool(values.get("watchFolderEnabled", s.watch_folder_enabled))
        s.watch_folder_path = str(values.get("watchFolderPath", s.watch_folder_path)).strip()

        s.disk_space_warning_enabled = bool(values.get("diskSpaceEnabled", s.disk_space_warning_enabled))
        s.disk_space_warning_threshold_mb = int(values.get("diskSpaceThresholdMb", s.disk_space_warning_threshold_mb))

        s.auto_shutdown_enabled = bool(values.get("shutdownEnabled", s.auto_shutdown_enabled))
        s.auto_shutdown_action = str(values.get("shutdownAction", s.auto_shutdown_action))
        s.auto_shutdown_delay_seconds = int(values.get("shutdownDelaySeconds", s.auto_shutdown_delay_seconds))

        s.pause_on_battery_enabled = bool(values.get("batteryPauseEnabled", s.pause_on_battery_enabled))

        s.provenance_manifest_enabled = bool(
            values.get("provenanceManifestEnabled", s.provenance_manifest_enabled)
        )

        s.memory_governor_enabled = bool(values.get("memoryGovernorEnabled", s.memory_governor_enabled))
        s.memory_governor_threshold_percent = int(
            values.get("memoryGovernorThresholdPercent", s.memory_governor_threshold_percent)
        )

        s.idle_bandwidth_reduction_enabled = bool(
            values.get("idleBandwidthReductionEnabled", s.idle_bandwidth_reduction_enabled)
        )
        s.idle_bandwidth_reduction_minutes = int(
            values.get("idleBandwidthReductionMinutes", s.idle_bandwidth_reduction_minutes)
        )

        s.known_disk_automation_enabled = bool(values.get("knownDiskEnabled", s.known_disk_automation_enabled))

        s.peer_reputation_enabled = bool(values.get("peerReputationEnabled", s.peer_reputation_enabled))
        s.lan_peer_cache_enabled = bool(values.get("lanPeerCacheEnabled", s.lan_peer_cache_enabled))

        s.save()
        # Disk-space monitor re-reads settings on its own timer tick, no
        # explicit apply call needed. The bandwidth schedule, though, is
        # cached in-memory by the scheduler -- nudge it so a currently
        # active window re-evaluates against the new values immediately.
        self._bandwidth_scheduler.settings_changed()
        return {"ok": True}

    @Slot(result="QVariantList")
    def getDecisionJournal(self) -> list:
        entries = self._decision_journal_service.recent_entries(100)
        return [{"timestamp": e.get("timestamp", ""), "text": e.get("text", "")} for e in entries]
