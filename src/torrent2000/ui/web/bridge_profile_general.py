"""QWebChannel bridge backing the Profile tab's "General" group -- mirrors
GeneralSettingsSection/AudioSection in profile_sections.py exactly: same
fields, same save-on-click batching for most of them, and the same three
live-apply exceptions (theme, appearance_mode, language) plus AudioSection's
volume slider, each applied and persisted immediately on change rather than
batched into Save (see profile_sections.py's module docstring for why).
"""

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.config.settings import Settings
from torrent2000.engine import startup_registration
from torrent2000.engine.session_manager import SessionManager
from torrent2000.i18n.translator import LANGUAGE_LABELS, set_language
from torrent2000.ui.theme.theme_manager import appearance_mode_labels

# The 34 real-CSS charter themes (see plan: idempotent-gathering-fern.md,
# "34 thèmes"), each a folder under resources/web/spike/themes/<id>/tokens.css.
# Deliberately NOT theme_manager.py's THEME_LABELS (the native QSS 7-theme
# list) -- that system is being phased out. 7 of these 34 ids intentionally
# match a native theme_id (luna_xp/win7_aero/win10_fluent/win11_mica/
# win95_classic/macos_modern/cccp_soviet) because engine-level business logic
# (CCCP's "no downloading" rule, macOS's stats-leveling weight) keys off
# those exact strings -- reusing them keeps that logic working untouched.
# The other 27 are brand new themes with no native counterpart.
WEB_THEME_LABELS: list[tuple[str, str]] = [
    ("Windows XP (Luna)", "luna_xp"),
    ("Windows 7 (Aero)", "win7_aero"),
    ("Windows 10 (Fluent)", "win10_fluent"),
    ("Windows 11 (Fluent 2)", "win11_mica"),
    ("Windows 95", "win95_classic"),
    ("macOS 26 (Tahoe Liquid Glass)", "macos_modern"),
    ("Soviétique productiviste (Constructivisme)", "cccp_soviet"),
    ("Windows 8.1 (Metro)", "windows-8"),
    ("Amiga Workbench", "amiga-workbench"),
    ("Art déco (Paris 1925)", "art-deco"),
    ("Bauhaus (Dessau)", "bauhaus"),
    ("BeOS R5", "beos-r5"),
    ("Blueprint (cyanotype)", "blueprint"),
    ("CDE Motif", "cde-motif"),
    ("ChromeOS (Material Google)", "chromeos"),
    ("Frutiger Aero (2004-2013)", "frutiger-aero"),
    ("KDE Plasma (Breeze)", "kde-plasma"),
    ("Linux (GNOME Adwaita)", "gnome-adwaita"),
    ("Linux Mint (Cinnamon Mint-Y)", "linux-mint"),
    ("Mac OS 9 (Platinum)", "macos-9"),
    ("Mac OS X 10.0 (Aqua Cheetah)", "macos-x-aqua"),
    ("Mac OS X Leopard (métal unifié)", "macos-x-leopard"),
    ("Macintosh System 1 (1984)", "macintosh-system-1"),
    ("Memphis (Milano 1981)", "memphis"),
    ("NeXTSTEP", "nextstep"),
    ("Palm OS (LCD monochrome)", "palm-os"),
    ("Soviétique cosmique (Rétrofuturisme)", "soviet-cosmic"),
    ("Suisse international (Zurich 1957)", "swiss-international"),
    ("Synthwave (Outrun)", "synthwave"),
    ("TUI DOS (Turbo Vision)", "tui-dos"),
    ("Terminal phosphore (P1)", "terminal-phosphor"),
    ("Ubuntu (Yaru)", "ubuntu"),
    ("Ubuntu Unity (Ambiance)", "ubuntu-unity"),
    ("Web-brutalisme", "web-brutalism"),
]


class ProfileGeneralBridge(QObject):
    themeChanged = Signal(str, str)  # theme_id, appearance_mode
    languageChanged = Signal(str)  # language code
    volumeChanged = Signal(int)  # 0-100, drives AnthemPlayer.set_volume

    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings

    @Slot(result="QVariantMap")
    def getSettings(self) -> dict:
        s = self._settings
        return {
            "defaultDownloadDir": s.default_download_dir,
            "downloadRateLimitKbps": s.download_rate_limit_kbps,
            "uploadRateLimitKbps": s.upload_rate_limit_kbps,
            "maxActiveDownloads": s.max_active_downloads,
            "dangerAutoExcludeThreshold": s.danger_auto_exclude_threshold,
            "notificationsEnabled": s.notifications_enabled,
            "launchAtStartup": s.launch_at_startup,
            "checkForUpdates": s.check_for_updates,
            "minimizeToTray": s.minimize_to_tray,
            "theme": s.theme,
            "appearanceMode": s.appearance_mode,
            "language": s.language,
            "audioVolume": s.audio_volume,
        }

    @Slot("QVariantMap", result="QVariantMap")
    def saveSettings(self, values: dict) -> dict:
        s = self._settings
        s.default_download_dir = str(values.get("defaultDownloadDir", s.default_download_dir)).strip() or s.default_download_dir
        s.download_rate_limit_kbps = int(values.get("downloadRateLimitKbps", s.download_rate_limit_kbps))
        s.upload_rate_limit_kbps = int(values.get("uploadRateLimitKbps", s.upload_rate_limit_kbps))
        s.max_active_downloads = max(1, min(100, int(values.get("maxActiveDownloads", s.max_active_downloads))))
        s.danger_auto_exclude_threshold = max(
            0, min(100, int(values.get("dangerAutoExcludeThreshold", s.danger_auto_exclude_threshold)))
        )
        s.notifications_enabled = bool(values.get("notificationsEnabled", s.notifications_enabled))
        new_launch_at_startup = bool(values.get("launchAtStartup", s.launch_at_startup))
        if new_launch_at_startup != s.launch_at_startup:
            # Only touch the registry when the checkbox actually changed --
            # every Save in this section used to rewrite it unconditionally.
            # Trade-off: set_launch_at_startup(True) also refreshes the
            # stored launch command (sys.executable) whenever it runs, so an
            # install manually moved to a new path only gets that implicit
            # repair by explicitly toggling this checkbox again, not on
            # every unrelated Save -- acceptable given the installer uses a
            # fixed install path.
            startup_registration.set_launch_at_startup(new_launch_at_startup)
        s.launch_at_startup = new_launch_at_startup
        s.check_for_updates = bool(values.get("checkForUpdates", s.check_for_updates))
        s.minimize_to_tray = bool(values.get("minimizeToTray", s.minimize_to_tray))
        # theme/appearance_mode/language/audio_volume are intentionally NOT
        # written here -- they live-apply and persist immediately on change
        # via their own dedicated slots below.
        s.save()
        return {"ok": True}

    @Slot(result=bool)
    def getLaunchAtStartupActual(self) -> bool:
        # Reflects the real HKCU Run key rather than the possibly-stale saved
        # setting -- if the user (or a reinstall) removed it by hand, this
        # should show unchecked rather than lying about it.
        return startup_registration.is_launch_at_startup_enabled()

    @Slot(result="QVariantList")
    def getThemeOptions(self) -> list:
        return [{"id": theme_id, "label": label} for label, theme_id in WEB_THEME_LABELS]

    @Slot(result="QVariantList")
    def getAppearanceModeOptions(self) -> list:
        return [{"id": mode_id, "label": label} for label, mode_id in appearance_mode_labels()]

    @Slot(result="QVariantList")
    def getLanguageOptions(self) -> list:
        return [{"id": code, "label": label} for label, code in LANGUAGE_LABELS]

    @Slot(str)
    def setTheme(self, theme_id: str) -> None:
        if not theme_id:
            return
        self._settings.theme = theme_id
        self._settings.save()
        # CCCP's "no downloading" rule takes effect immediately, pausing any
        # in-progress downloads -- same as native (see enforce_theme_download_policy).
        self._session_manager.enforce_theme_download_policy()
        self.themeChanged.emit(theme_id, self._settings.appearance_mode)

    @Slot(str)
    def setAppearanceMode(self, mode: str) -> None:
        if not mode:
            return
        self._settings.appearance_mode = mode
        self._settings.save()
        self.themeChanged.emit(self._settings.theme, mode)

    @Slot(str)
    def setLanguage(self, lang: str) -> None:
        if not lang:
            return
        self._settings.language = lang
        self._settings.save()
        set_language(lang)
        self.languageChanged.emit(lang)

    @Slot(int)
    def setVolume(self, value: int) -> None:
        self._settings.audio_volume = value
        self._settings.save()
        self.volumeChanged.emit(value)
