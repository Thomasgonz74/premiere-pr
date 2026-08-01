from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QSizeGrip, QTabWidget, QVBoxLayout, QWidget

from torrent2000 import APP_NAME
from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.stats.service import StatsService
from torrent2000.ui.tabs.add_tab import AddTorrentTab
from torrent2000.ui.tabs.downloads_tab import DownloadsTab
from torrent2000.ui.tabs.profile_tab import ProfileTab
from torrent2000.ui.widgets.xp_title_bar import XPTitleBar


class MainWindow(QMainWindow):
    def __init__(
        self, session_manager: SessionManager, stats_service: StatsService, settings: Settings, parent=None
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._stats_service = stats_service
        self._settings = settings

        self.setWindowTitle(APP_NAME)
        # The native Windows title bar can't be restyled to look like XP
        # (QSS doesn't reach OS-owned window chrome), so the window runs
        # frameless and XPTitleBar below stands in for it.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.resize(980, 640)

        central = QWidget(self)
        central.setObjectName("centralWidget")
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._title_bar = XPTitleBar(APP_NAME, central)
        outer_layout.addWidget(self._title_bar)

        tabs = QTabWidget(central)
        tabs.setObjectName("mainTabs")
        tabs.addTab(AddTorrentTab(session_manager, settings), "Ajout / Analyse")
        tabs.addTab(DownloadsTab(session_manager), "Téléchargements")
        tabs.addTab(ProfileTab(session_manager, stats_service, settings), "Profil")
        outer_layout.addWidget(tabs, 1)

        # Frameless windows lose the OS's edge-resize handles; a QSizeGrip
        # in the corner is the low-risk way to get drag-to-resize back
        # without hooking native WM_NCHITTEST edge detection.
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 2, 2)
        grip_row.addStretch(1)
        self._size_grip = QSizeGrip(central)
        grip_row.addWidget(self._size_grip, 0, Qt.AlignBottom | Qt.AlignRight)
        outer_layout.addLayout(grip_row)

        self.setCentralWidget(central)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            self._title_bar.refresh_maximize_glyph()

    def closeEvent(self, event) -> None:
        self._stats_service.shutdown()
        self._session_manager.shutdown()
        super().closeEvent(event)
