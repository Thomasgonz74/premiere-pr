"""Phase 0/1+ spike entry point (see plan: idempotent-gathering-fern.md).
Separate from run.py on purpose -- this must not touch or destabilize the
shipped v1.1.1 QWidget app while the QWebEngineView architecture is being
validated. Run: python run_web_spike.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_history_db_path, get_rss_seen_db_path, get_stats_db_path
from torrent2000.config.settings import Settings
from torrent2000.engine.anthem_player import AnthemPlayer
from torrent2000.engine.antivirus_scan_service import AntivirusScanService
from torrent2000.engine.auto_shutdown_service import AutoShutdownService
from torrent2000.engine.battery_pause_service import BatteryPauseService
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.engine.decision_journal import DecisionJournalService
from torrent2000.engine.disk_reconnect_service import DiskReconnectService
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor
from torrent2000.engine.idle_activity_service import IdleActivityService
from torrent2000.engine.known_disk_service import KnownDiskService, KnownDiskStore
from torrent2000.engine.memory_pressure_governor import MemoryPressureGovernor
from torrent2000.engine.network_profile_switcher import NetworkProfileStore, NetworkProfileSwitcherService
from torrent2000.engine.remote_server import RemoteAccessServer
from torrent2000.engine.routing_rules import RoutingRuleStore
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.rss_seen_store import RssSeenStore
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.settings_profiles import SettingsProfileStore
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.single_instance import SingleInstanceGuard
from torrent2000.engine.update_checker import UpdateChecker
from torrent2000.engine.watch_folder_service import WatchFolderService
from torrent2000.logging_setup import _setup_logging
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.history_store import HistoryStore
from torrent2000.stats.service import StatsService
from torrent2000.stats.store import StatsStore
from torrent2000.ui.notifications import NotificationService
from torrent2000.ui.web.spike_window import SpikeWindow


def main() -> int:
    app = QApplication(sys.argv)
    # Checked before any other startup work so a second launch -- e.g.
    # double-clicking another .torrent file while the app is already open,
    # now that the installer registers that file association -- forwards
    # its argument and exits as cheaply as possible instead of racing a
    # second libtorrent session (mirrors native torrent2000.app.main()).
    guard = SingleInstanceGuard()
    if not guard.try_become_primary(sys.argv[1] if len(sys.argv) > 1 else ""):
        return 0

    _setup_logging()
    settings = Settings.load()
    session_manager = SessionManager(settings)
    share_limit_service = ShareLimitService(session_manager, settings)
    watch_folder_service = WatchFolderService(session_manager, settings)
    battery_pause_service = BatteryPauseService(session_manager, settings)
    disk_reconnect_service = DiskReconnectService(session_manager, settings)
    antivirus_scan_service = AntivirusScanService(session_manager, settings)
    update_checker = UpdateChecker(settings)

    stats_store = StatsStore(get_stats_db_path())
    stats_service = StatsService(stats_store, session_manager, settings)
    history_store = HistoryStore(get_history_db_path())
    history_service = HistoryService(history_store, session_manager)
    rss_seen_store = RssSeenStore(get_rss_seen_db_path())
    rss_feed_service = RssFeedService(session_manager, settings, rss_seen_store)
    memory_pressure_governor = MemoryPressureGovernor(session_manager, settings, rss_feed_service, history_service)
    bandwidth_scheduler = BandwidthScheduler(session_manager, settings)
    idle_activity_service = IdleActivityService(bandwidth_scheduler, settings)
    disk_space_monitor = DiskSpaceMonitor(session_manager, settings)
    remote_access_server = RemoteAccessServer(session_manager, settings)
    if settings.remote_access_enabled:
        remote_access_server.start()
    routing_rule_store = RoutingRuleStore()
    settings_profile_store = SettingsProfileStore()
    auto_shutdown_service = AutoShutdownService(session_manager, settings)
    anthem_player = AnthemPlayer(settings.audio_volume)
    known_disk_store = KnownDiskStore()
    known_disk_service = KnownDiskService(known_disk_store, settings)
    network_profile_store = NetworkProfileStore()
    network_profile_switcher_service = NetworkProfileSwitcherService(
        session_manager, settings, network_profile_store, settings_profile_store
    )
    decision_journal_service = DecisionJournalService(session_manager, known_disk_service, disk_space_monitor)

    window = SpikeWindow(
        session_manager,
        settings,
        share_limit_service,
        stats_service=stats_service,
        history_service=history_service,
        rss_feed_service=rss_feed_service,
        bandwidth_scheduler=bandwidth_scheduler,
        disk_space_monitor=disk_space_monitor,
        remote_access_server=remote_access_server,
        routing_rule_store=routing_rule_store,
        settings_profile_store=settings_profile_store,
        auto_shutdown_service=auto_shutdown_service,
        anthem_player=anthem_player,
        update_checker=update_checker,
        known_disk_store=known_disk_store,
        known_disk_service=known_disk_service,
        network_profile_store=network_profile_store,
        decision_journal_service=decision_journal_service,
    )
    # Second-launch arguments arriving later, forwarded by SingleInstanceGuard
    # (empty when a later launch had none, e.g. the exe was just reopened).
    guard.argument_received.connect(lambda source: window.open_source(source) if source else None)
    if len(sys.argv) > 1:
        window.open_source(sys.argv[1])
    window.show()

    notification_service = NotificationService(session_manager, share_limit_service, settings, app)

    def _restore_window() -> None:
        window.show()
        window.activateWindow()

    notification_service.show_requested.connect(_restore_window)
    notification_service.quit_requested.connect(app.quit)

    def _shutdown() -> None:
        share_limit_service.flush_pending_save()
        remote_access_server.stop()
        session_manager.shutdown()

    app.aboutToQuit.connect(_shutdown)
    # Delayed so the update check's network request doesn't compete with the
    # rest of startup (session restore, stats DB open, etc), same as native.
    QTimer.singleShot(3000, update_checker.check_now)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
